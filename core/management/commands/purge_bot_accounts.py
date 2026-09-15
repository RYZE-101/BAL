"""Bot-Accounts löschen (einmaliges Aufräumen nach Spam-Angriff).

Löscht User samt Ratings (CASCADE) und rechnet Scores/Ranking/Achievements
einmalig neu. Staff/Superuser werden NIEMALS gelöscht.

Standardmäßig nur Dry-Run (zeigt, was gelöscht würde)::

    python manage.py purge_bot_accounts
    python manage.py purge_bot_accounts --delete
    python manage.py purge_bot_accounts --delete --prefix probe_ --prefix verify_

Getroffen werden Usernamen, die auf Bot-Muster passen:
  - user_<10 hexzeichen>  (Standard-Bot-Schema, z.B. user_84150dade2)
  - zusätzlich per --prefix angegebene Präfixe (z.B. probe_, verify_)
"""

import re

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.signals import post_delete

from core import services
from core.models import Rating
from core.signals import recompute_score_on_rating_delete

BOT_PATTERN = re.compile(r"^user_[0-9a-f]{10}$")


def is_bot(username, extra_prefixes):
    if BOT_PATTERN.match(username):
        return True
    return any(username.startswith(p) for p in extra_prefixes)


class Command(BaseCommand):
    help = "Löscht Bot-Accounts (Dry-Run ohne --delete)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete", action="store_true",
            help="Wirklich löschen (ohne Flag nur Dry-Run).",
        )
        parser.add_argument(
            "--prefix", action="append", default=[],
            help="Zusätzlicher Username-Präfix (wiederholbar).",
        )

    def handle(self, *args, **options):
        do_delete = options["delete"]
        prefixes = options["prefix"]

        candidates = User.objects.filter(is_staff=False, is_superuser=False)
        victims = [u for u in candidates if is_bot(u.username, prefixes)]

        staff_hits = sum(
            1 for u in User.objects.filter(is_staff=True)
            if is_bot(u.username, prefixes)
        )
        rating_count = Rating.objects.filter(pupil__in=victims).count()

        self.stdout.write(
            f"Bot-Accounts: {len(victims)} "
            f"(davon {rating_count} mit Bewertungen)"
        )
        if staff_hits:
            self.stdout.write(
                self.style.WARNING(
                    f"{staff_hits} Staff-User passen aufs Muster "
                    f"und werden NICHT gelöscht."
                )
            )
        for u in victims[:20]:
            self.stdout.write(f"  - {u.username} ({u.email})")
        if len(victims) > 20:
            self.stdout.write(f"  ... und {len(victims) - 20} weitere")

        if not victims:
            self.stdout.write("Nichts zu tun.")
            return

        if not do_delete:
            self.stdout.write(
                self.style.NOTICE("Dry-Run – nichts gelöscht. Mit --delete ausführen.")
            )
            return

        # Per-Rating-Neuberechnung während des Bulk-Deletes abschalten
        # (Signal würde sonst pro Rating alles neu rechnen); danach einmalig.
        post_delete.disconnect(recompute_score_on_rating_delete, sender=Rating)
        try:
            with transaction.atomic():
                deleted, _ = User.objects.filter(pk__in=[u.pk for u in victims]).delete()
        finally:
            post_delete.connect(recompute_score_on_rating_delete, sender=Rating)

        services.refresh_all()
        self.stdout.write(
            self.style.SUCCESS(
                f"Fertig: {len(victims)} Accounts gelöscht "
                f"({deleted} DB-Zeilen inkl. Ratings/Antworten), "
                f"Scores/Ranking/Achievements neu berechnet."
            )
        )
