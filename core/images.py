"""Bild-Komprimierung für Profilfotos (kleine Dateien, schnelle Ladezeit).

Handy-Fotos (mehrere MB) würden jede Seite mit vielen Bildern bei
schlechtem WLAN ewig laden lassen. Darum: max. Kantenlänge, JPEG mit
moderater Qualität, progressiv (baut sich stufenweise auf).
"""
import os
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

MAX_DIMENSION = 1024  # längste Seite in px (reicht für 72–400 px Anzeige)
JPEG_QUALITY = 75


def compress_image(uploaded_file, max_dimension=MAX_DIMENSION,
                   quality=JPEG_QUALITY):
    """Verkleinert ein Upload-Bild und gibt es als JPEG-ContentFile zurück.

    Behebt EXIF-Rotation (Handy-Fotos), ersetzt Transparenz durch Weiß.
    Bei jedem Fehler wird das Original zurückgegeben — ein Upload darf
    nie an der Komprimierung scheitern.
    """
    try:
        img = Image.open(uploaded_file)
        img = ImageOps.exif_transpose(img)
        if img.mode in ('RGBA', 'LA', 'PA', 'P'):
            if img.mode == 'P':
                img = img.convert('RGBA')
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True,
                 progressive=True)
        buf.seek(0)
        base = os.path.splitext(
            getattr(uploaded_file, 'name', None) or 'photo')[0]
        try:
            uploaded_file.seek(0)  # Eingang zurückspulen (Höflichkeit)
        except Exception:
            pass
        return ContentFile(buf.read(), name=base + '.jpg')
    except Exception:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
        return uploaded_file
