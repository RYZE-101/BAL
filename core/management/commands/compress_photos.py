import os

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from PIL import Image

from core.images import MAX_DIMENSION, compress_image
from core.models import Teacher

# Bereits kleine JPEGs nicht erneut komprimieren (Qualitätsverlust).
SKIP_BYTES = 300 * 1024


class Command(BaseCommand):
    help = ('Komprimiert alle bestehenden Lehrerfotos (max. 1024 px, JPEG). '
            'Einmalig nach dem Einführen der Upload-Komprimierung ausführen.')

    def handle(self, *args, **options):
        done = skipped = failed = 0
        for teacher in Teacher.objects.exclude(photo='').exclude(photo=None):
            old_path = getattr(teacher.photo, 'path', None)
            if not old_path or not os.path.isfile(old_path):
                failed += 1
                self.stderr.write(f'FEHLT: {teacher.name} ({teacher.photo})')
                continue
            try:
                with Image.open(old_path) as im:
                    already_small = (
                        im.format == 'JPEG'
                        and max(im.size) <= MAX_DIMENSION
                        and os.path.getsize(old_path) <= SKIP_BYTES
                    )
                if already_small:
                    skipped += 1
                    continue
                with open(old_path, 'rb') as f:
                    compressed = compress_image(
                        ContentFile(f.read(),
                                    name=os.path.basename(old_path)))
                teacher.photo.save(compressed.name, compressed, save=True)
                new_path = teacher.photo.path
                if new_path != old_path and os.path.isfile(old_path):
                    os.remove(old_path)  # z.B. altes .png nach .jpg-Wechsel
                done += 1
                self.stdout.write(
                    f'OK: {teacher.name} '
                    f'({os.path.getsize(new_path) // 1024} KB)')
            except Exception as exc:  # ein Bild darf den Lauf nie stoppen
                failed += 1
                self.stderr.write(f'FEHLER bei {teacher.name}: {exc}')
        self.stdout.write(self.style.SUCCESS(
            f'Fertig: {done} komprimiert, {skipped} übersprungen, '
            f'{failed} fehlgeschlagen.'))
