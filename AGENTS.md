# AGENTS.md – BAL Server-Tutorial (für Codex)

Diese Datei erklärt, wie du dich mit dem Produktionsserver verbindest und dort
arbeitest. Lies sie vollständig, bevor du irgendeinen Server-Befehl ausführst.

## 1. Verbindung

Produktionsserver: `212.227.39.26` (Ubuntu). Key-only SSH als `root`.
Der Key des Users liegt bereits auf der Maschine, auf der du läufst:

```bash
ssh -i ~/.ssh/id_ed25519 -o ConnectTimeout=15 root@212.227.39.26 '<command>'
```

Regeln:

- **Ein Befehl pro SSH-Call**, sauber quoten.
- Es gibt **kein Passwort**. Wenn SSH fehlschlägt: diagnostizieren und erklären,
  aber **nichts** an `sshd_config` oder `authorized_keys` ändern ohne explizite
  Bestätigung des Users.
- **Nie** nach Credentials jagen (macOS Keychain, Git-Credential-Store etc.)
  ohne vorher zu fragen.

## 2. Layout auf dem Server (`/opt/bal`)

- `manage.py`, `core/`, `bal/`, `templates/`, `static/` → App-Code (per rsync deployed)
- `deploy.sh` → Schritte nach jedem Sync (venv, pip, migrate, collectstatic,
  `chown www-data`, Restart `bal`, nginx-Reload)
- `.last_deploy` → UTC-Zeitstempel des letzten Deploys (Verifikation)
- `.venv/` → Python-Venv (**bleibt auf dem Server**, nie anfassen/löschen)
- `.env` (mode 600) → Secrets (**nie lesen/ausgeben/einchecken**)
- `db.sqlite3` → Produktionsdatenbank (**niemals nach Git, niemals per rsync anfassen**)
- `media/` → Uploads, z. B. `media/teachers/` (**niemals nach Git**)
- `staticfiles/` → generiert per `collectstatic` (**niemals nach Git**)
- `db.sqlite3.backup*` → lokale DB-Backups (**niemals committen**)

## 3. Services

- `bal.service` (systemd, User `www-data`): Gunicorn auf `unix:/run/bal/bal.sock`
- nginx-Site `bal`: Port 80, `server_name 212.227.39.26`;
  `/static/` → `/opt/bal/staticfiles/`, `/media/` → `/opt/bal/media/`
- Timer: `bal-snapshot.timer` (00:05 UTC), `bal-rules.timer` (00:10 UTC)

## 4. Deploy-Flow (Normalfall: NICHT manuell auf dem Server arbeiten)

Deploys laufen über **GitHub Actions** bei Push auf `main`
(`.github/workflows/deploy.yml`):

1. `rsync --delete` nach `/opt/bal/`, exkludiert sind:
   `.git`, `.github`, `.venv`, `db.sqlite3`, `media`, `staticfiles`, `.env`, `cache`
2. `bash /opt/bal/deploy.sh` auf dem Server

Heißt: Code-Änderungen gehören in die lokale Kopie, committen, auf `main`
pushen — der Server aktualisiert sich selbst. Manuell per SSH nur debuggen,
wenn Actions fehlschlägt oder Live-Diagnose nötig ist.

Verifikation nach jedem Deploy:

```bash
ssh -i ~/.ssh/id_ed25519 root@212.227.39.26 'cat /opt/bal/.last_deploy; systemctl is-active bal; curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1/'
```

`.last_deploy` muss frisch sein, Service `active`, Homepage HTTP 200.

## 5. Read-only Checks (immer zuerst, vor jeder Änderung)

```bash
ssh -i ~/.ssh/id_ed25519 root@212.227.39.26 'systemctl status bal --no-pager -l | head -12'
ssh -i ~/.ssh/id_ed25519 root@212.227.39.26 'journalctl -u bal --no-pager -n 30'
ssh -i ~/.ssh/id_ed25519 root@212.227.39.26 'systemctl list-timers bal-snapshot.timer bal-rules.timer --no-pager'
ssh -i ~/.ssh/id_ed25519 root@212.227.39.26 'nginx -t && ls -la /opt/bal/media/teachers/ | head'
```

## 6. Rezepte

- **„Läuft der Server?"** → Verifikationsbefehl aus Abschnitt 4.
- **„Logs ansehen"** → `journalctl -u bal --no-pager -n 50` (ggf. `-f`).
- **„Migration anwenden"** → läuft automatisch via `deploy.sh`. Falls du von Hand
  etwas an Schema/Daten änderst: **vorher Backup + zeigen**:
  ```bash
  ssh -i ~/.ssh/id_ed25519 root@212.227.39.26 'cd /opt/bal && cp db.sqlite3 db.sqlite3.backup-vor-<grund> && ls -la db.sqlite3*'
  ```
  Danach verifizieren, z. B. `python manage.py showmigrations core`.
- **„Django-Shell auf dem Server"** →
  ```bash
  ssh -i ~/.ssh/id_ed25519 root@212.227.39.26 'cd /opt/bal && source .venv/bin/activate && set -a && source .env && set +a && python manage.py shell -c "..."'
  ```
- **„Testdaten anlegen/löschen"** → nur via Django-Shell auf dem Server.
  Echte Lehrer/Bewertungen **nie** ohne explizite Bestätigung löschen.
- **„Lehrer-Avatare"** → Standard-Avatare liegen im Repo unter
  `static/img/teachers/avatar-1..6.svg`, Fallback-Logik in
  `templates/core/_teacher_photo.html` + `Teacher.avatar_static`
  (`core/models.py`). `media/teachers/` muss leer bleiben.

## 7. Harte Sicherheitsregeln (nicht verhandelbar)

1. `/root/.ssh/authorized_keys` **nur** per Append (`>>`), **nie** per Skript
   umschreiben. Vorher aktuellen Inhalt + exakt anzuhängende Zeile zeigen und
   auf Bestätigung warten.
2. Der Personal-Key des Users (`... rameen@Ramin.local`) ist installiert —
   diese Zeile **nie** anfassen/löschen. Deploy-Key-Marker:
   `bal-deploy@github-actions` (ebenfalls nur append).
3. Zielzustand key-only (`PasswordAuthentication no`,
   `PermitRootLogin prohibit-password`) nur herstellen, wenn beide Keys
   bewiesen funktionieren — und nur nach expliziter Bestätigung.
4. `media/` und `db.sqlite3` gehen nie durch Git; rsync fasst sie nie an.
5. Server soll schlank bleiben: keine Backups, kein `.git`/`.github`, kein
   Cache dort horten — alles gehört ins GitHub-Repo `RYZE-101/BAL`.

## 8. Troubleshooting

- Gunicorn `Permission denied` auf Socket → `bal.service` braucht
  `RuntimeDirectory=bal` (Socket muss in www-data-schreibbarem Dir liegen).
- Stale `/run/bal.sock` nach Unit-Änderungen → `rm -f`, `daemon-reload`, `bal` restarten.
- `DisallowedHost` in Django-Shell-Tests → erst `/opt/bal/.env` sourcen oder
  `Client(HTTP_HOST="212.227.39.26")` / `127.0.0.1` nutzen.
- Admin 500 beim Teacher-Speichern mit Foto → nur neu hochgeladene Dateien
  validieren (`self.files`), nie `photo.content_type` auf `ImageFieldFile`.
