from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from . import services
from .images import compress_image
from .models import (
    Achievement,
    AchievementRule,
    Rating,
    RatingAnswer,
    RatingQuestion,
    Subject,
    Teacher,
    TeacherAchievement,
    TeacherScore,
)


class TeacherAdminForm(forms.ModelForm):
    """Validierung + Komprimierung für Profilbild-Uploads.

    Neue Uploads werden sofort auf max. 1024 px / JPEG q75 verkleinert,
    damit die Seiten auch bei schlechtem WLAN schnell laden."""

    ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
    MAX_SIZE = 5 * 1024 * 1024  # 5 MB (VOR der Komprimierung geprüft)

    class Meta:
        model = Teacher
        fields = '__all__'

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        uploaded = self.files.get('photo')
        # Nur bei NEU hochgeladenen Dateien validieren; eine bestehende
        # Datei (ImageFieldFile) beim Bearbeiten hat kein content_type.
        if uploaded:
            if uploaded.content_type not in self.ALLOWED_TYPES:
                raise ValidationError('Nur JPG, PNG oder WEBP sind erlaubt.')
            if uploaded.size > self.MAX_SIZE:
                raise ValidationError('Das Bild darf maximal 5 MB groß sein.')
            return compress_image(uploaded)
        return photo


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name',)
    prepopulated_fields = {'slug': ('name',)}


class RatingInline(admin.TabularInline):
    model = Rating
    extra = 0


class TeacherAchievementInline(admin.TabularInline):
    """Manuelle Zuweisung/Entfernung von Achievements je Lehrkraft."""

    model = TeacherAchievement
    extra = 0
    verbose_name = 'Auszeichnung'
    verbose_name_plural = 'Auszeichnungen'


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    form = TeacherAdminForm
    list_display = ('name', 'is_active', 'photo_preview', 'score')
    list_filter = ('is_active', 'subjects')
    search_fields = ('name', 'subjects__name', 'bio')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('subjects',)
    readonly_fields = ('photo_preview',)
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'subjects', 'is_active')}),
        ('Profil & Foto', {'fields': ('photo', 'photo_preview', 'bio')}),
    )
    inlines = [RatingInline, TeacherAchievementInline]

    @admin.display(description='Foto')
    def photo_preview(self, obj):
        if not obj.photo:
            return '–'
        return format_html(
            '<img src="{}" alt="{}" style="width:72px;height:72px;object-fit:cover;'
            'border-radius:14px;border:1px solid rgba(0,0,0,.12)">',
            obj.photo.url,
            obj.name,
        )

    @admin.display(description='Gesamtscore')
    def score(self, obj):
        try:
            return f'{obj.score.avg_overall:.2f} (Rang {obj.score.rank})'
        except TeacherScore.DoesNotExist:
            return '–'


class RatingAnswerInline(admin.TabularInline):
    model = RatingAnswer
    extra = 0
    can_delete = False
    verbose_name = 'Antwort'
    verbose_name_plural = 'Antworten'

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    """Bewertungen lesbar für Moderation; Felder schreibgeschützt, Löschen erlaubt."""

    list_display = ('pupil', 'teacher', 'overall', 'created_at', 'updated_at')
    list_filter = ('teacher', 'created_at')
    search_fields = ('pupil__username', 'teacher__name')
    date_hierarchy = 'created_at'
    readonly_fields = ('pupil', 'teacher', 'overall', 'created_at', 'updated_at')
    inlines = [RatingAnswerInline]

    def has_add_permission(self, request):
        return False


class RatingQuestionForm(forms.ModelForm):
    """Formular für Bewertungsfragen: Text prominent + verständlich."""

    text = forms.CharField(
        help_text='Der Fragetext, wie er im Bewertungsformular angezeigt wird.'
    )

    class Meta:
        model = RatingQuestion
        fields = '__all__'


@admin.register(RatingQuestion)
class RatingQuestionAdmin(admin.ModelAdmin):
    """Fragen im Admin verwalten: Text, Reihenfolge, aktiv/inaktiv.

    Löschen wird verhindert (historische Antworten bleiben erhalten); eine
    Frage wird stattdessen über is_active=False deaktiviert. Alle Fragen
    (ursprüngliche wie neu hinzugefügte) werden identisch behandelt.
    """

    form = RatingQuestionForm
    list_display = ('text', 'order', 'key', 'is_active', 'answer_count')
    list_editable = ('is_active',)
    list_filter = ('is_active',)
    search_fields = ('text', 'key')
    ordering = ('order', 'id')
    fieldsets = (
        ('Frage', {'fields': ('text',)}),
        ('Einstellungen', {'fields': ('key', 'order', 'is_active')}),
    )

    @admin.display(description='Antworten')
    def answer_count(self, obj):
        return obj.answers.count()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TeacherScore)
class TeacherScoreAdmin(admin.ModelAdmin):
    list_display = (
        'teacher', 'rating_count', 'avg_overall', 'rank', 'previous_rank'
    )
    actions = ['refresh_scores']

    @admin.action(description='Scores neu berechnen')
    def refresh_scores(self, request, queryset):
        for obj in queryset:
            services.recompute_teacher_score(obj.teacher_id)
        services.update_ranking()
        services.update_achievements()
        self.message_user(request, 'Scores aktualisiert.')


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'sort_order')


@admin.register(TeacherAchievement)
class TeacherAchievementAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'achievement', 'is_current', 'manually_removed', 'awarded_at')
    list_filter = ('is_current', 'achievement', 'manually_removed')
    actions = ['mark_manually_removed']

    @admin.action(description='Manuell entfernen (unterdrückt Auto-Neuvergabe)')
    def mark_manually_removed(self, request, queryset):
        updated = queryset.update(is_current=False, manually_removed=True)
        self.message_user(request, f'{updated} Auszeichnung(en) manuell entfernt.')


@admin.register(AchievementRule)
class AchievementRuleAdmin(admin.ModelAdmin):
    list_display = (
        'achievement', 'condition_type', 'threshold_value', 'question',
        'duration_days', 'is_active',
    )
    list_editable = ('is_active',)
    list_filter = ('condition_type', 'is_active')
    fieldsets = (
        (None, {
            'fields': ('achievement', 'condition_type', 'is_active'),
        }),
        ('Bedingung', {
            'fields': (
                'threshold_value',
                'question',
                'duration_days',
            ),
            'description': (
                'TOP_N_RANK: threshold_value = N (z.B. 3 für Top-3). '
                'CATEGORY_SCORE_ABOVE: threshold_value = Mindest-Score (z.B. 8.5), '
                'question = die zu prüfende Bewertungsfrage. '
                'CATEGORY_SCORE_BELOW: threshold_value = Höchst-Score (z.B. 4.0, '
                'Score muss darunter liegen, fehlende Werte zählen nicht). '
                'duration_days: leer = sofort bei Erfüllung, sonst Tage durchgängig erfüllt.'
            ),
        }),
    )


class UserRatingInline(admin.TabularInline):
    """Schreibgeschützte Übersicht: welcher Schüler welche Lehrkräfte bewertet hat."""

    model = Rating
    fk_name = 'pupil'
    extra = 0
    can_delete = False
    verbose_name = 'Bewertung'
    verbose_name_plural = 'Bewertungen (schreibgeschützt)'

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False


admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    """Gruppen verwalten, inkl. Übersicht der zugehörigen Benutzer."""

    list_display = ('name', 'member_count')
    search_fields = ('name',)
    filter_horizontal = ('permissions',)
    readonly_fields = ('members_list',)
    fieldsets = (
        ('Gruppe', {'fields': ('name',)}),
        ('Mitglieder', {'fields': ('members_list',)}),
    )

    @admin.display(description='Mitglieder')
    def member_count(self, obj):
        return obj.user_set.count()

    @admin.display(description='Mitglieder')
    def members_list(self, obj):
        members = obj.user_set.order_by('username')
        if not members:
            return format_html('<em>Noch keine Mitglieder.</em>')
        items = ''.join(format_html('<li>{}</li>', u.username) for u in members)
        return format_html('<ul class="bal-group-members">{}</ul>', items)


admin.site.unregister(User)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Schüler-Accounts mit voller CRUD-Fähigkeit plus Bewertungs-Übersicht."""

    inlines = [UserRatingInline]
