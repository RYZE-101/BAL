# BAL – Notes & Entscheidungen

Kurze Notizen, damit nachvollziehbar bleibt, was warum gemacht wurde.

## Architektur
- **Eine App `core`** statt vieler Mini-Apps – bewusst einfach gehalten (nicht over-engineered).
  Sollte das Projekt wachsen, können Modelle/Views leicht in eigene Apps extrahiert werden.
- **Score-Caching:** `TeacherScore` (1:1 zu Teacher) speichert aggregierte Scores + Rang +
  vorherigen Rang. Wird bei jeder Bewertung/Update neu berechnet (services.py), damit
  Ranking/Achievements/Profil schnell sind (keine teuren Live-Aggregationen).
- **Ranking-Auf/Abstieg:** `previous_rank` wird bei `update_ranking()` vor dem neuen Rang
  gesichert. `rank_delta = rank - previous_rank` (negativ = Aufstieg).

## Bewertungsskala
- **1–10** per Slider. Begründung: feinere Granularität als 1–5 → bessere
  Differenzierung und sinnvollere Rangfolge bei ähnlichen Lehrkräften.

## Dynamische Bewertungsfragen (seit Migration 0002)
- **`RatingQuestion`** (text, key, order, is_active) verwaltet die Fragen im Admin;
  Fragen werden nicht gelöscht, sondern über `is_active=False` deaktiviert
  (historische Antworten bleiben erhalten). Löschen ist im Admin deaktiviert.
- **`RatingAnswer`** (rating, question, value 1–10): eine Bewertung (`Rating`)
  besteht aus einer Antwort pro zum Bewertungszeitpunkt aktiver Frage
  (normalisiertes Muster statt fester Spalten).
- **Score-Logik (bewusste Entscheidung):** `avg_overall` einer Lehrkraft =
  Durchschnitt **aller** `RatingAnswer`-Werte, unabhängig davon, ob die Frage
  aktuell aktiv ist. So bleiben historische Antworten in der Wertung erhalten
  und eine Deaktivierung ändert vergangene Scores nicht rückwirkend.
- **Kategorie-Scores** (`avg_interest` … `avg_digitalization`) werden nur für
  Fragen mit klassischem `key` berechnet (für Ranking-Achievements wie
  "Fairste"/"Interessanteste"). Neue Fragen ohne Key tragen nur zu `avg_overall` bei.
- Profilseite zeigt die Kategorien **dynamisch** (alle aktiven Fragen nach `order`).
- Migration 0002 überführt die alten 5 festen `q_*`-Felder verlustfrei in
  `RatingAnswer` (5 Fragen mit Keys anlegen, jede Rating-Zeile → 5 Antworten).

## Anti-Spam (MVP)
- Django-Auth (Login Pflicht zum Bewerten). `unique_together(pupil, teacher)` verhindert
  Mehrfachabstimmung (Update statt Duplikat).
- E-Mail-Verifizierung ist als Option vorgesehen, aber NICHT Teil des MVP (Email-Backend
  = console). TODO, falls Spam relevant wird.

## Achievements
- Bewusst als DB-Model (`Achievement`) statt hartkodiert → erweiterbar im Admin.
- Auto-Vergabe in `services.update_achievements()`: Platz 1, Top 3, Fairste,
  Modernste, Interessanteste. Historie bleibt via `is_current`-Flag erhalten.

## Bekannte Baustellen / nächste Schritte
- E-Mail-Verifizierung für Registrierung.
- SSL/HTTPS: sobald (Sub-)Domain vorhanden → Certbot (Nginx-Config dafür vorbereitet).
- Umstieg SQLite → PostgreSQL: nur ENGINE/Config tauschen.
- Optional: Anonymität der Bewertungen sauber dokumentieren (wer sieht was).
