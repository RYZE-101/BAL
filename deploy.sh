#!/usr/bin/env bash
# Wird nach jedem rsync durch GitHub Actions auf dem Server ausgeführt.
# Erwartet: bereits nach /opt/bal geklonte/rsyncte Codebasis.
set -euo pipefail

APP_DIR="/opt/bal"
VENV="$APP_DIR/.venv"
DJANGO_USER="www-data"

cd "$APP_DIR"

# Virtuelle Umgebung anlegen, falls nicht vorhanden
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"

# Abhängigkeiten installieren
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Env-Datei laden (wird beim Server-Setup erzeugt, nicht versioniert)
if [ -f "$APP_DIR/.env" ]; then
    set -a
    source "$APP_DIR/.env"
    set +a
fi

# Datenbank-Migrationen anwenden
python manage.py migrate --noinput

# Statische Dateien sammeln
python manage.py collectstatic --noinput

# Upload-/Static-Verzeichnisse für den Web-User freigeben
mkdir -p media staticfiles
chown -R "$DJANGO_USER":"$DJANGO_USER" media staticfiles db.sqlite3 2>/dev/null || true

# Gunicorn-Dienst neu starten (fängt neuen Code auf)
if systemctl list-unit-files 'bal.service' >/dev/null 2>&1; then
    systemctl restart bal
fi

# Nginx-Konfiguration neu laden
systemctl reload nginx 2>/dev/null || systemctl restart nginx

echo "Deploy abgeschlossen."
