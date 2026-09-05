from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Erstellt den täglichen Rang/Score-Snapshot je Lehrkraft.'

    def handle(self, *args, **options):
        from core.models import TeacherRankSnapshot, TeacherScore

        today = timezone.localdate()
        keys = ('interest', 'productivity', 'fairness', 'atmosphere', 'digitalization')
        count = 0
        for s in TeacherScore.objects.all():
            cat = {}
            for k in keys:
                v = getattr(s, f'avg_{k}', None)
                if v is not None:
                    cat[k] = v
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
