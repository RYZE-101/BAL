from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Erstellt den täglichen Rang/Score-Snapshot je Lehrkraft.'

    def handle(self, *args, **options):
        from core.models import RatingAnswer, RatingQuestion, TeacherRankSnapshot, TeacherScore
        from django.db.models import Avg

        today = timezone.localdate()
        # Dynamisch: Kategorie-Scores für ALLE aktiven Fragen (nicht fix 5).
        active_ids = list(
            RatingQuestion.objects.filter(is_active=True).values_list('id', flat=True)
        )
        rows = (
            RatingAnswer.objects
            .values('rating__teacher_id', 'question_id')
            .annotate(avg=Avg('value'))
        )
        cat_by_teacher = {}
        for row in rows:
            cat_by_teacher.setdefault(row['rating__teacher_id'], {})[
                str(row['question_id'])] = row['avg']

        count = 0
        for s in TeacherScore.objects.all():
            cat = cat_by_teacher.get(s.teacher_id, {})
            # nur aktive Fragen speichern
            cat = {k: v for k, v in cat.items() if int(k) in active_ids}
            TeacherRankSnapshot.objects.update_or_create(
                teacher=s.teacher,
                date=today,
                defaults={
                    'rank': s.rank,
                    'score': s.avg_overall,
                    'category_scores': cat,
                },
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(
            f'Snapshot für {today} erstellt ({count} Lehrkräfte).'
        ))
