import os

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Rating, Teacher, TeacherScore


@receiver(post_delete, sender=Rating)
def recompute_score_on_rating_delete(sender, instance, **kwargs):
    """Berechnet Score/Ranking/Achievements nach dem Löschen einer Bewertung neu.

    Verhindert 'Geister-Daten' von gelöschten Ratings in den Durchschnitten.
    Aktualisiert nur einen BEREITS VORHANDENEN Score (kein Anlegen neuer
    Zeilen): so entsteht während einer Lehrkraft-Kaskaden-Löschung keine
    verwaiste TeacherScore-Referenz (FK-Fehler).
    """
    teacher_id = instance.teacher_id
    try:
        if not Teacher.objects.filter(pk=teacher_id).exists():
            return
        if not TeacherScore.objects.filter(teacher_id=teacher_id).exists():
            return  # kein Score vorhanden -> nichts zu aktualisieren
        from . import services
        services.recompute_teacher_score(teacher_id)
        services.update_ranking()
        services.update_achievements()
    except Exception:
        pass


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
