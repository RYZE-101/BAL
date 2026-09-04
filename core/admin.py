from django.contrib import admin

from . import services
from .models import (
    Achievement,
    Rating,
    Subject,
    Teacher,
    TeacherAchievement,
    TeacherScore,
)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name',)
    prepopulated_fields = {'slug': ('name',)}


class RatingInline(admin.TabularInline):
    model = Rating
    extra = 0


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'score')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('subjects',)
    inlines = [RatingInline]

    @admin.display(description='Gesamtscore')
    def score(self, obj):
        try:
            return f'{obj.score.avg_overall:.2f} (Rang {obj.score.rank})'
        except TeacherScore.DoesNotExist:
            return '–'


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ('pupil', 'teacher', 'overall', 'updated_at')
    list_filter = ('teacher',)


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
