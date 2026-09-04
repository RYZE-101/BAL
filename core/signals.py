import os

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Teacher


@receiver(post_delete, sender=Teacher)
def delete_teacher_photo(sender, instance, **kwargs):
    """Entfernt die Profilbild-Datei beim Löschen einer Lehrkraft.

    Greift bei Einzel- und Bulk-Löschungen (Admin, QuerySet.delete()).
    """
    photo = getattr(instance, 'photo', None)
    if not photo:
        return
    path = getattr(photo, 'path', None)
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
