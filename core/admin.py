from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from . import services
from .models import (
    Achievement,
    Rating,
    Subject,
    Teacher,
    TeacherAchievement,
    TeacherScore,
)


class TeacherAdminForm(forms.ModelForm):
    """Validierung für Profilbild-Uploads (Größe & Format)."""

    ALLOWED_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
    MAX_SIZE = 5 * 1024 * 1024  # 5 MB

    class Meta:
        model = Teacher
        fields = '__all__'

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if photo:
            if photo.content_type not in self.ALLOWED_TYPES:
                raise ValidationError('Nur JPG, PNG oder WEBP sind erlaubt.')
            if photo.size > self.MAX_SIZE:
                raise ValidationError('Das Bild darf maximal 5 MB groß sein.')
        return photo


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name',)
    prepopulated_fields = {'slug': ('name',)}


class RatingInline(admin.TabularInline):
    model = Rating
    extra = 0


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
    inlines = [RatingInline]

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


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    """Bewertungen lesbar für Moderation; Felder schreibgeschützt, Löschen erlaubt."""

    list_display = ('pupil', 'teacher', 'overall', 'created_at', 'updated_at')
    list_filter = ('teacher', 'created_at')
    search_fields = ('pupil__username', 'teacher__name')
    date_hierarchy = 'created_at'
    readonly_fields = (
        'pupil', 'teacher',
        'q_interest', 'q_productivity', 'q_fairness',
        'q_atmosphere', 'q_digitalization',
        'overall', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
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
    list_display = ('teacher', 'achievement', 'is_current', 'awarded_at')
    list_filter = ('is_current', 'achievement')


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


admin.site.unregister(User)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Schüler-Accounts mit voller CRUD-Fähigkeit plus Bewertungs-Übersicht."""

    inlines = [UserRatingInline]
