from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .forms import RatingForm, UserSignupForm
from .models import Achievement, Rating, Teacher, TeacherAchievement, TeacherScore


def home(request):
    teachers = Teacher.objects.filter(is_active=True).select_related('score')
    total_teachers = teachers.count()
    total_ratings = Rating.objects.count()
    top3 = list(
        TeacherScore.objects.filter(rating_count__gt=0)
        .select_related('teacher')
        .order_by('-avg_overall', 'teacher__name')[:3]
    )
    return render(request, 'core/home.html', {
        'teachers': teachers,
        'total_teachers': total_teachers,
        'total_ratings': total_ratings,
        'top3': top3,
    })


def teacher_list(request):
    teachers = (
        Teacher.objects.filter(is_active=True)
        .select_related('score')
        .prefetch_related('subjects')
        .order_by('name')
    )
    return render(request, 'core/teacher_list.html', {'teachers': teachers})


def teacher_detail(request, slug):
    teacher = get_object_or_404(
        Teacher.objects.select_related('score').prefetch_related(
            'subjects', 'ratings', 'achievements__achievement'
        ),
        slug=slug,
        is_active=True,
    )
    my_rating = None
    rating_form = None
    if request.user.is_authenticated:
        my_rating = Rating.objects.filter(
            pupil=request.user, teacher=teacher
        ).first()
        rating_form = RatingForm(instance=my_rating)
    return render(request, 'core/teacher_detail.html', {
        'teacher': teacher,
        'my_rating': my_rating,
        'rating_form': rating_form,
        'achievements': teacher.achievements.filter(is_current=True),
    })


@login_required
def rate_teacher(request, slug):
    teacher = get_object_or_404(Teacher, slug=slug, is_active=True)
    existing = Rating.objects.filter(pupil=request.user, teacher=teacher).first()
    if request.method == 'POST':
        form = RatingForm(request.POST, instance=existing)
        if form.is_valid():
            rating = form.save(commit=False)
            rating.pupil = request.user
            rating.teacher = teacher
            rating.save()
            # Scores & Ranking & Achievements aktualisieren
            services.recompute_teacher_score(teacher.pk)
            services.update_ranking()
            services.update_achievements()
            return redirect('teacher_detail', slug=teacher.slug)
    else:
        form = RatingForm(instance=existing)
    return render(request, 'core/rate_teacher.html', {
        'teacher': teacher,
        'form': form,
    })


def ranking(request):
    scores = _ranked_scores()
    return render(request, 'core/ranking.html', {'scores': scores})


def _ranked_scores():
    scores = list(
        TeacherScore.objects.filter(rating_count__gt=0)
        .select_related('teacher')
        .order_by('rank')
    )
    for score in scores:
        score.delta = services.rank_delta(score)
    return scores


def ranking_partial(request):
    """HTML-Fragment für das Live-Polling der Ranking-Liste."""
    scores = _ranked_scores()
    return render(request, 'core/_ranking_list.html', {'scores': scores})


def achievements(request):
    achievements = Achievement.objects.prefetch_related(
        'holders__teacher', 'holders__achievement'
    ).all()
    return render(request, 'core/achievements.html', {'achievements': achievements})


def achievement_detail(request, slug):
    achievement = get_object_or_404(
        Achievement.objects.prefetch_related('holders__teacher'), slug=slug
    )
    current = achievement.holders.filter(is_current=True)
    former = achievement.holders.filter(is_current=False)
    return render(request, 'core/achievement_detail.html', {
        'achievement': achievement,
        'current': current,
        'former': former,
    })


def signup(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = UserSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
    else:
        form = UserSignupForm()
    return render(request, 'registration/signup.html', {'form': form})
