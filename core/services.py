"""Score-Berechnung, Ranking-Aktualisierung und Achievement-Vergabe.

Diese Logik ist bewusst zentralisiert und getestet (siehe core/tests.py).
"""

from django.db import transaction
from django.db.models import Avg

from .models import Rating, RatingAnswer, TeacherScore

# Achievement-Slugs, die wir automatisch vergeben (Definitionen im Admin anlegen)
ACH_TOP1 = 'top-1'
ACH_TOP3 = 'top-3'
ACH_FAIREST = 'fairest'
ACH_MOST_DIGITAL = 'most-digital'
ACH_MOST_INTERESTING = 'most-interesting'


def recompute_teacher_score(teacher_id):
    """Aggregiert alle Ratings einer Lehrkraft neu in TeacherScore.

    Gesamtscore = Durchschnitt ALLER Antworten (RatingAnswer) der Lehrkraft,
    unabhängig davon, ob die zugehörige Frage aktuell aktiv ist (so bleiben
    historische Antworten für die Vergleichbarkeit erhalten).
    Per-Kategorie-Scores werden NICHT gespeichert, sondern dynamisch je Frage
    aus den RatingAnswers abgefragt (siehe category_score() / Snapshot).
    """
    teacher_score, _ = TeacherScore.objects.get_or_create(teacher_id=teacher_id)
    rating_count = Rating.objects.filter(teacher_id=teacher_id).count()
    answers = RatingAnswer.objects.filter(rating__teacher_id=teacher_id)

    teacher_score.rating_count = rating_count
    if rating_count == 0:
        teacher_score.avg_overall = 0
    else:
        overall = answers.aggregate(models_avg=Avg('value'))['models_avg']
        teacher_score.avg_overall = round(float(overall or 0), 2)
    teacher_score.save()
    return teacher_score


def category_score(teacher_id, question_id):
    """Durchschnittswert einer Lehrkraft für eine bestimmte Frage (dynamisch)."""
    return round(float(
        RatingAnswer.objects.filter(
            rating__teacher_id=teacher_id, question_id=question_id
        ).aggregate(models_avg=Avg('value'))['models_avg'] or 0
    ), 2)


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


def _best_by_question_key(key):
    """Lehrkraft + Durchschnitt mit dem höchsten Wert in der Frage mit ``key``.

    Dynamisch aus den RatingAnswers berechnet (kein gespeicherter
    Kategorie-Score). Liefert (teacher_obj, avg) oder (None, 0).
    """
    from .models import Teacher

    row = (
        RatingAnswer.objects.filter(question__key=key)
        .values('rating__teacher_id')
        .annotate(avg=Avg('value'))
        .order_by('-avg', 'rating__teacher_id')
        .first()
    )
    if not row or not row['avg']:
        return None, 0
    try:
        teacher = Teacher.objects.get(pk=row['rating__teacher_id'])
    except Teacher.DoesNotExist:
        return None, 0
    return teacher, row['avg']


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
    fairest, fairest_avg = _best_by_question_key('fairness')
    if fairest and fairest_avg > 0:
        _revoke_current(ACH_FAIREST, keep_teacher_id=fairest.pk)
        _award(ACH_FAIREST, fairest.pk)

    # Most digital
    digital, digital_avg = _best_by_question_key('digitalization')
    if digital and digital_avg > 0:
        _revoke_current(ACH_MOST_DIGITAL, keep_teacher_id=digital.pk)
        _award(ACH_MOST_DIGITAL, digital.pk)

    # Most interesting
    interesting, interest_avg = _best_by_question_key('interest')
    if interesting and interest_avg > 0:
        _revoke_current(ACH_MOST_INTERESTING, keep_teacher_id=interesting.pk)
        _award(ACH_MOST_INTERESTING, interesting.pk)

    # Optional: Platz 1 im Verlauf zählen (Top-1-Historie) über TeacherAchievement


def refresh_all():
    """Kompletter Refresh: Scores → Ranking → Achievements."""
    recompute_all_scores()
    update_ranking()
    update_achievements()


# ---------------------------------------------------------------
# Regelbasiertes Achievement-System
# ---------------------------------------------------------------
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    AchievementRule,
    TeacherAchievement,
    TeacherRankSnapshot,
    TeacherScore,
)


def _current_rank_by_teacher():
    return {
        s.teacher_id: s.rank
        for s in TeacherScore.objects.filter(rating_count__gt=0)
    }


def _category_scores_by_teacher():
    """{teacher_id: {question_id(str): avg}} dynamisch aus den RatingAnswers."""
    rows = (
        RatingAnswer.objects
        .values('rating__teacher_id', 'question_id')
        .annotate(avg=Avg('value'))
    )
    out = {}
    for row in rows:
        out.setdefault(row['rating__teacher_id'], {})[str(row['question_id'])] = row['avg']
    return out


def _snapshot_meets(rule, snap):
    """Prüft, ob eine Regel in einem einzelnen Snapshot erfüllt ist."""
    if rule.condition_type == AchievementRule.ConditionType.TOP_N_RANK:
        return snap.rank is not None and snap.rank <= rule.threshold_value
    if rule.condition_type == AchievementRule.ConditionType.CATEGORY_SCORE_ABOVE:
        if rule.question_id is None:
            return False
        return snap.category_scores.get(str(rule.question_id), 0) >= rule.threshold_value
    return False


def _current_satisfying_ids(rule, rank_by_teacher, cat_by_teacher):
    """Lehrkraft-IDs, die die Regel AKTUELL erfüllen (ohne Zeitfenster)."""
    ids = set()
    for tid in rank_by_teacher.keys():
        if rule.condition_type == AchievementRule.ConditionType.TOP_N_RANK:
            rank = rank_by_teacher[tid]
            if rank is not None and rank <= rule.threshold_value:
                ids.add(tid)
        elif rule.condition_type == AchievementRule.ConditionType.CATEGORY_SCORE_ABOVE:
            if rule.question_id is None:
                continue
            val = cat_by_teacher.get(tid, {}).get(str(rule.question_id))
            if val is not None and val >= rule.threshold_value:
                ids.add(tid)
    return ids


def _duration_satisfying_ids(rule):
    """Lehrkraft-IDs, die die Regel in ALLEN Snapshots der letzten N Tage erfüllen."""
    today = timezone.localdate()
    start = today - timedelta(days=rule.duration_days - 1)
    snaps = list(
        TeacherRankSnapshot.objects.filter(date__gte=start, date__lte=today)
        .order_by('teacher', 'date')
    )
    from collections import defaultdict
    by_teacher = defaultdict(list)
    for s in snaps:
        by_teacher[s.teacher_id].append(s)
    satisfying = set()
    for tid, teacher_snaps in by_teacher.items():
        if len(teacher_snaps) < rule.duration_days:
            continue
        if all(_snapshot_meets(rule, s) for s in teacher_snaps):
            satisfying.add(tid)
    return satisfying


@transaction.atomic
def evaluate_achievement_rules():
    """Bewertet alle aktiven Regeln und vergibt/entzieht Achievements.

    - null-duration: sofort bei aktueller Erfüllung.
    - duration_days: nur bei durchgängiger Erfüllung in den letzten N Tagen.
    - Keine Doppelvergabe (is_current=True vorhanden).
    - manually_removed: unterdrückt Neuvergabe, bis die Bedingung einmal NICHT
      mehr erfüllt war (dann wird das Flag zurückgesetzt).
    """
    today = timezone.localdate()
    rank_by_teacher = _current_rank_by_teacher()
    cat_by_teacher = _category_scores_by_teacher()

    for rule in AchievementRule.objects.filter(is_active=True):
        if rule.duration_days:
            satisfying = _duration_satisfying_ids(rule)
        else:
            satisfying = _current_satisfying_ids(rule, rank_by_teacher, cat_by_teacher)

        existing = TeacherAchievement.objects.filter(achievement=rule.achievement)
        existing_by_teacher = {ta.teacher_id: ta for ta in existing}

        # Entziehen / manually_removed zurücksetzen bei Nichterfüllung
        for ta in existing:
            if ta.teacher_id in satisfying:
                if ta.manually_removed:
                    continue  # manuell entfernt -> nicht neu vergeben
                if not ta.is_current:
                    ta.is_current = True
                    ta.save()
            else:
                changed = False
                if ta.is_current:
                    ta.is_current = False
                    changed = True
                if ta.manually_removed:
                    ta.manually_removed = False  # Streak gebrochen
                    changed = True
                if changed:
                    ta.save()

        # Neu vergeben
        for tid in satisfying:
            if tid in existing_by_teacher:
                continue
            TeacherAchievement.objects.create(
                teacher_id=tid,
                achievement=rule.achievement,
                is_current=True,
                manually_removed=False,
            )
    return today
