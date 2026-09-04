"""Legt Demo-Daten an: Fächer, Lehrkräfte, Schüler und Zufallsbewertungen.

Nutzung: python manage.py seed_demo [--ratings 20]
"""

import random
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from core import services
from core.models import Achievement, Rating, Subject, Teacher


SUBJECTS = [
    'Mathematik', 'Deutsch', 'Englisch', 'Physik', 'Biologie', 'Chemie',
    'Geschichte', 'Sport', 'Kunst', 'Musik', 'Informatik', 'Französisch',
]

TEACHERS = [
    ('Anna Schmidt', ['Mathematik', 'Physik']),
    ('Michael Weber', ['Deutsch', 'Geschichte']),
    ('Laura Fischer', ['Englisch', 'Französisch']),
    ('Thomas Müller', ['Biologie', 'Chemie']),
    ('Julia Becker', ['Kunst', 'Musik']),
    ('David Hoffmann', ['Sport', 'Biologie']),
    ('Sarah Wagner', ['Informatik', 'Mathematik']),
    ('Jan Neumann', ['Geschichte', 'Deutsch']),
]

ACHIEVEMENTS = [
    ('top-1', 'Platz 1', 'Aktuell auf Platz 1 im Ranking.', '🥇', 1),
    ('top-3', 'Top 3', 'Aktuell unter den Top 3.', '🏅', 2),
    ('fairest', 'Fairste Lehrkraft', 'Höchster Fairness-Score.', '⚖️', 3),
    ('most-digital', 'Modernste Lehrkraft', 'Höchster Digitalisierungs-Score.', '💻', 4),
    ('most-interesting', 'Interessanteste Lehrkraft', 'Höchster Interessens-Score.', '✨', 5),
]

QUESTIONS = [
    'q_interest', 'q_productivity', 'q_fairness', 'q_atmosphere', 'q_digitalization',
]


class Command(BaseCommand):
    help = 'Erzeugt Demo-Daten für Entwicklung und Tests.'

    def add_arguments(self, parser):
        parser.add_argument('--ratings', type=int, default=20)

    def handle(self, *args, **options):
        count = options['ratings']

        for name in SUBJECTS:
            Subject.objects.get_or_create(name=name)

        for t_name, subs in TEACHERS:
            teacher, _ = Teacher.objects.get_or_create(name=t_name)
            for s in subs:
                teacher.subjects.add(Subject.objects.get(name=s))

        for slug, name, desc, icon, order in ACHIEVEMENTS:
            Achievement.objects.get_or_create(
                slug=slug,
                defaults={'name': name, 'description': desc, 'icon': icon, 'sort_order': order},
            )

        # Demo-Schüler
        pupils = []
        for i in range(1, 11):
            user, _ = User.objects.get_or_create(
                username=f'schueler{i}',
                defaults={'email': f'schueler{i}@example.de'},
            )
            user.set_password('test1234')
            user.save()
            pupils.append(user)

        teachers = list(Teacher.objects.all())
        random.seed(42)
        for pupil in pupils:
            for teacher in random.sample(teachers, random.randint(3, len(teachers))):
                Rating.objects.update_or_create(
                    pupil=pupil,
                    teacher=teacher,
                    defaults={
                        q: random.randint(4, 10) for q in QUESTIONS
                    },
                )

        services.refresh_all()
        self.stdout.write(self.style.SUCCESS(
            f'Seed abgeschlossen: {Subject.objects.count()} Fächer, '
            f'{Teacher.objects.count()} Lehrkräfte, {Rating.objects.count()} Bewertungen.'
        ))
