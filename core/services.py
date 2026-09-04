"""Score-Berechnung, Ranking-Aktualisierung und Achievement-Vergabe.

Diese Logik ist bewusst zentralisiert und getestet (siehe core/tests.py).
"""

from django.db import transaction
from django.db.models import Avg

from .models import Rating, TeacherScore

RATING_FIELDS = [
    'q_interest', 'q_productivity', 'q_fairness',
    'q_atmosphere', 'q_digitalization',
]

# Achievement-Slugs, die wir automatisch vergeben (Definitionen im Admin anlegen)
ACH_TOP1 = 'top-1'
ACH_TOP3 = 'top-3'
ACH_FAIREST = 'fairest'
ACH_MOST_DIGITAL = 'most-digital'
ACH_MOST_INTERESTING = 'most-interesting'


def _field_label(field):
    labels = {
        'q_interest': 'Interesse',
        'q_productivity': 'Produktivität',
        'q_fairness': 'Fairness',
        'q_atmosphere': 'Atmosphäre',
        'q_digitalization': 'Digitalisierung',
    }
    return labels[field]


def recompute_teacher_score(teacher_id):
    """Aggregiert alle Ratings einer Lehrkraft neu in TeacherScore."""
    teacher_score, _ = TeacherScore.objects.get_or_create(teacher_id=teacher_id)
    ratings = Rating.objects.filter(teacher_id=teacher_id)

    teacher_score.rating_count = ratings.count()
    if teacher_score.rating_count == 0:
        teacher_score.avg_interest = 0
        teacher_score.avg_productivity = 0
        teacher_score.avg_fairness = 0
        teacher_score.avg_atmosphere = 0
        teacher_score.avg_digitalization = 0
        teacher_score.avg_overall = 0
    else:
        for field in RATING_FIELDS:
            avg = ratings.aggregate(models_avg=Avg(field))['models_avg']
            setattr(teacher_score, f'avg_{field[2:]}', round(float(avg), 2))
        teacher_score.avg_overall = round(
            sum(getattr(teacher_score, f'avg_{f[2:]}') for f in RATING_FIELDS) / len(RATING_FIELDS),
            2,
        )
    teacher_score.save()
    return teacher_score


def recompute_all_scores():
    """Rechnet alle Lehrkraft-Scores neu (nach Massen-Import o. Ä.)."""
    from .models import Teacher

    for teacher in Teacher.objects.all():
        recompute_teacher_score(teacher.pk)


@transaction.atomic
def update_ranking():
    """Ordnet alle Lehrkräfte nach avg_overall, sichert den vorherigen Rang.

    Nur Lehrkräfte mit mindestens einer Bewertung werden gerankt.
    """
    scores = list(
        TeacherScore.objects.filter(rating_count__gt=0).order_by(
            '-avg_overall', 'teacher__name'
        )
    )
    for index, score in enumerate(scores, start=1):
        score.previous_rank = score.rank
        score.rank = index
        score.save()
    return scores


def rank_delta(score):
    """Rangveränderung (neu - alt). Negativ = Aufstieg, positiv = Abstieg."""
    if score.previous_rank is None:
        return 0
    return score.rank - score.previous_rank


def _current_top(limit):
    return list(
        TeacherScore.objects.filter(rating_count__gt=0)
        .order_by('-avg_overall', 'teacher__name')[:limit]
    )


def _best_by_field(field):
    return (
        TeacherScore.objects.filter(rating_count__gt=0)
        .order_by(f'-avg_{field}', '-rating_count', 'teacher__name')
        .first()
    )


def _award(achievement_slug, teacher_id):
    from .models import Achievement, TeacherAchievement

    try:
        achievement = Achievement.objects.get(slug=achievement_slug)
    except Achievement.DoesNotExist:
        return
    TeacherAchievement.objects.update_or_create(
        teacher_id=teacher_id,
        achievement=achievement,
        defaults={'is_current': True},
    )


def _revoke_current(achievement_slug, keep_teacher_id=None):
    from .models import Achievement, TeacherAchievement

    try:
        achievement = Achievement.objects.get(slug=achievement_slug)
    except Achievement.DoesNotExist:
        return
    holders = TeacherAchievement.objects.filter(
        achievement=achievement, is_current=True
    )
    if keep_teacher_id:
        holders = holders.exclude(teacher_id=keep_teacher_id)
    holders.update(is_current=False)


@transaction.atomic
def update_achievements():
    """Vergibt die aktuellen (positionsabhängigen) Achievements neu.

    Geschichte bleibt über is_current=False erhalten.
    """
    from .models import Achievement, TeacherScore

    # Platz 1
    top1 = _current_top(1)
    if top1:
        _revoke_current(ACH_TOP1, keep_teacher_id=top1[0].teacher_id)
        _award(ACH_TOP1, top1[0].teacher_id)

    # Top 3
    top3 = _current_top(3)
    top3_ids = {s.teacher_id for s in top3}
    _revoke_current(ACH_TOP3)
    for score in top3:
        _award(ACH_TOP3, score.teacher_id)

    # Fairest
    fairest = _best_by_field('fairness')
    if fairest and fairest.avg_fairness > 0:
        _revoke_current(ACH_FAIREST, keep_teacher_id=fairest.teacher_id)
        _award(ACH_FAIREST, fairest.teacher_id)

    # Most digital
    digital = _best_by_field('digitalization')
    if digital and digital.avg_digitalization > 0:
        _revoke_current(ACH_MOST_DIGITAL, keep_teacher_id=digital.teacher_id)
        _award(ACH_MOST_DIGITAL, digital.teacher_id)

    # Most interesting
    interesting = _best_by_field('interest')
    if interesting and interesting.avg_interest > 0:
        _revoke_current(ACH_MOST_INTERESTING, keep_teacher_id=interesting.teacher_id)
        _award(ACH_MOST_INTERESTING, interesting.teacher_id)

    # Optional: Platz 1 im Verlauf zählen (Top-1-Historie) über TeacherAchievement


def refresh_all():
    """Kompletter Refresh: Scores → Ranking → Achievements."""
    recompute_all_scores()
    update_ranking()
    update_achievements()
