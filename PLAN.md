# BAL – Roadmap

Lehrer-Ranking-Plattform. Status und Reihenfolge der Arbeit.

## Tech-Entscheidungen
- **DB:** SQLite zum Start (einfacher Betrieb), Models PostgreSQL-freundlich gehalten
  (BigAutoField, keine SQLite-Hacks). Umstieg: ENGINE in settings.py tauschen + env-Config.
- **WSGI:** Gunicorn (statt uWSGI) – moderner Standard, einfacher mit systemd + Nginx.
- **DB-Empfehlung (langfristig):** PostgreSQL – robust, gleichzeitige Schreibzugriffe,
  nur ein Config-Switch nötig. Fürs MVP reicht SQLite.
- **Bewertungsskala:** 1–10 (Slider). Feiner als 1–5 → bessere Differenzierung im Ranking.
- **Anti-Spam:** Django-Auth + 1 Bewertung pro Schüler & Lehrkraft (unique_together).
  E-Mail-Verifizierung später als Option (Backend ist console → echte Verifizierung = TODO).

## Status

### ✅ 1. Grundgerüst (Django, Models, Admin)
- Django 6.1, App `core`. Models: Subject, Teacher, Rating, TeacherScore,
  Achievement, TeacherAchievement.
- Admin mit Score-Anzeige und "Scores neu berechnen"-Action.
- `seed_demo`-Management-Kommando für Testdaten.

### ✅ 2. Schüler-Auth
- Django built-in auth (login/logout/signup). Unique pupil+teacher pro Rating.

### ✅ 3. Lehrkraft-Profile + Übersicht
- Raster-Ansicht (responsive), Detailseite mit Foto-Platzhalter, Fächer, Score-Balken.

### ✅ 4. Bewertungssystem + Score-Berechnung
- 5 Slider-Fragen (1–10), Gesamtscore, aggregierte Scores.
- Getestet (core/tests.py: Score-Berechnung, unique constraint, Ranking, Achievements).

### ✅ 5. Live-Ranking
- Podest Top 3 (Gold/Silber/Bronze), Polling alle 10s (JS fetch auf Partial),
  Auf/Abstieg via previous_rank (▲/▼ + Zahl).

### ✅ 6. Achievements
- Achievement-Model (erweiterbar, nicht im Template hartkodiert).
- Automatische Vergabe: Platz 1, Top 3, Fairste, Modernste, Interessanteste.

### ✅ 7. Design (Apple-Look, Light/Dark)
- Design-Tokens (CSS-Variablen), prefers-color-scheme + manueller Toggle (localStorage),
  responsive, dezent Animationen.

### ⬜ 8. Server-Setup + CI/CD
- Nginx (HTTP, SSL-fähig vorbereitet), Gunicorn, systemd, GitHub Actions.

### ⬜ 9. Deploy + E2E-Test

### ⬜ 10. Abschluss-Review
