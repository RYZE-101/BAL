"""Baseline-Bewertungen: 5/5/5/… für Lehrkräfte (Dämpfung gegen Einzel-Votes).

Ohne Baseline ergibt 1 einzelner 10er-Vote sofort 10,0 (und 1er sofort ~1).
Eine 5er-Bewertung pro Lehrkraft zieht Einzel-Votes zur Mitte.

Standard: nur Lehrkräfte GANZ OHNE Bewertungen (echte Schnitte bleiben
unverändert). Mit --all bekommen alle eine zusätzliche 5er-Bewertung::

    python manage.py baseline_ratings
    python manage.py baseline_ratings --all
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from core import services
from core.models import Rating, RatingAnswer, RatingQuestion, Teacher

SYSTEM_USERNAME = "bal-system"
BASELINE_VALUE = 5


class Command(BaseCommand):
    help = "Baseline-5er-Bewertungen für Lehrkräfte ohne Ratings (--all: für alle)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all", action="store_true",
            help="Auch Lehrkräften MIT Bewertungen eine 5er-Bewertung geben.",
        )

    def handle(self, *args, **options):
        questions = list(
            RatingQuestion.objects.filter(is_active=True).order_by("order", "id")
        )
        if not questions:
            self.stdout.write(self.style.ERROR("Keine aktiven Fragen – Abbruch."))
            return

        system, _ = User.objects.get_or_create(
            username=SYSTEM_USERNAME,
            defaults={"email": "", "is_active": False},
        )
        if system.has_usable_password():
            system.set_unusable_password()
            system.save()

        teachers = Teacher.objects.filter(is_active=True).annotate(
            n_ratings=Count("ratings")
        )
        if options["all"]:
            targets = list(teachers)
            skipped = 0
        else:
            targets = [t for t in teachers if t.n_ratings == 0]
            skipped = teachers.count() - len(targets)

        created = 0
        with transaction.atomic():
            for teacher in targets:
                if Rating.objects.filter(
                    pupil=system, teacher=teacher
                ).exists():
                    skipped += 1
                    continue
                rating = Rating.objects.create(pupil=system, teacher=teacher)
                RatingAnswer.objects.bulk_create(
                    RatingAnswer(rating=rating, question=q, value=BASELINE_VALUE)
                    for q in questions
                )
                created += 1

        services.refresh_all()
        self.stdout.write(
            self.style.SUCCESS(
                f"Fertig: {created} Baseline-Bewertungen "
                f"(Wert {BASELINE_VALUE} auf {len(questions)} Fragen), "
                f"{skipped} übersprungen, Scores/Ranking neu berechnet."
            )
        )
