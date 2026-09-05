from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Bewertet Achievement-Regeln und vergibt/entzieht Achievements.'

    def handle(self, *args, **options):
        from core import services

        today = services.evaluate_achievement_rules()
        self.stdout.write(self.style.SUCCESS(
            f'Regeln für {today} ausgewertet.'
        ))
