```
██████╗  █████╗ ██╗
██╔══██╗██╔══██╗██║
██████╔╝███████║██║
██╔══██╗██╔══██║██║
██████╔╝██║  ██║███████╗
╚═════╝ ╚═╝  ╚═╝╚══════╝
```

**Bewertung. Ranking. Lehrkräfte.**

---

## Wie das hier überhaupt entstanden ist

Ehrlich gesagt: Es gab mal einen Vorgänger namens **"Evalu"** — die nüchterne Idee, dass Schüler\*innen ihre Lehrkräfte bewerten können. Klang nachweislich nach Excel, Steuererklärung und Schulkonferenz. Nicht gerade die Art von Projekt, bei der man nachts wach liegt und an den Code denkt.

Die eigentliche Initialzündung kam dann — natürlich — mitten im Unterricht. Beste Zeit für Nebenprojekt-Ideen ist bekanntlich der Unterricht selbst. Irgendwo zwischen Notizen und Nicken kam der Gedanke: *Was, wenn daraus nicht nur ein "bewerten und gut ist" wird, sondern ein echtes Live-Ranking?* Mit Auf- und Abstieg. Mit einer Top-3-Zelebration. Mit Achievements. 📊

Plötzlich war aus "Evalu" **BAL** geworden — und aus einem pflichtbewussten Feedback-Tool etwas, das man tatsächlich Lust hatte zu bauen.

---

## Was ist BAL?

BAL ist eine Plattform zum **Live-Ranking von Lehrkräften**, basierend auf anonymisierten Schülerbewertungen. Statt statischer Sterne gibt es ein dynamisches Ranking mit Auf-/Abstiegsanzeige, einer hervorgehobenen Top-3-Siegertreppe und einem Achievement-System — verpackt in ein schlichtes, Apple-inspiriertes Design mit Dark/Light Mode.

## Features

- **Konfigurierbare Bewertungsfragen** – Fragen werden im Admin verwaltet; hinzufügen, deaktivieren, Reihenfolge ändern. Kein Hardcoding, alles dynamisch.
- **Live-Ranking** – mit Rangauf-/abstieg und sanfter Aktualisierung.
- **Top-3-Zelebration** – klassische Siegertreppe mit Krone, Gold/Silber/Bronze.
- **Achievement-System** – manuell im Admin sowie **regelbasiert automatisch** (z. B. "Top 3", "Kategorie-Score über X"), optional zeitbasiert über tägliche Snapshots.
- **Schüler-Auth** – Registrierung/Login; Bewerten nur angemeldet.
- **Admin-Verwaltung** – Lehrkräfte, Fächer, Fragen, Regeln, Bewertungs-Moderation.
- **Dark/Light Mode** & vollständig **responsives Design**.

## Tech-Stack

- **Backend:** Django, SQLite (Postgres-tauglich vorbereitet)
- **Server:** Nginx (Reverse Proxy), Gunicorn (WSGI), systemd
- **Frontend:** Vanilla JavaScript + CSS (kein schweres Framework)
- **CI/CD:** GitHub Actions (automatischer Deploy bei Push auf `main`)

## Setup / Lokale Entwicklung

Voraussetzung: Python 3.10+.

```bash
# Repository klonen und in den Ordner wechseln
git clone https://github.com/RYZE-101/BAL.git
cd BAL

# Virtuelle Umgebung anlegen und aktivieren
python3 -m venv .venv
source .venv/bin/activate

# Abhängigkeiten installieren
pip install -r requirements.txt

# Umgebungsvariablen anlegen (.env)
#   DJANGO_SECRET_KEY=<geheimer Schlüssel>
#   DJANGO_DEBUG=True
#   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
cp .env.example .env   # falls vorhanden, sonst manuell anlegen

# Datenbank migrieren und Superuser anlegen
python manage.py migrate
python manage.py createsuperuser

# Entwicklungsserver starten
python manage.py runserver
```

Danach läuft die App unter `http://127.0.0.1:8000/`, das Admin-Interface unter `/admin/`.

## Lizenz

Dieses Projekt ist unter der [Apache License 2.0](LICENSE) lizenziert.

---

## Was kommt als Nächstes?

BAL war die erste Idee, die vom Whiteboard-Konzept bis in ein laufendes Projekt durchgezogen wurde — aber mit Sicherheit nicht die letzte. Es gibt bereits weitere Plattform-Ideen in der Pipeline, die auf dem gleichen Mix aus etwas Ernstem und etwas spielerisch Angepacktem aufbauen. Mehr dazu, sobald sie reif genug sind, gezeigt zu werden — schau also gern bald wieder auf meinem GitHub-Profil vorbei. 👀
