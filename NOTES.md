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
- **Score-Logik:** `avg_overall` einer Lehrkraft = Durchschnitt der Antworten zu
  den **aktuell aktiven** Fragen. Wird eine Frage deaktiviert, fließt sie
  sofort nicht mehr in den Score ein (historische Antworten bleiben in der DB
  erhalten, zählen aber nicht mehr mit). Bewusste Entscheidung, damit
  Deaktivierungen sofort wirksam werden.
- **Kategorie-Scores sind vollständig dynamisch:** Es gibt KEINE fest
  gespeicherten `avg_*`-Spalten mehr. `services.category_score(teacher_id,
  question_id)` berechnet den Durchschnitt je Frage on-the-fly aus den
  `RatingAnswer`s; Profil-Kategorien und Achievement-Regeln
  (`CATEGORY_SCORE_ABOVE`) beziehen sich auf `question_id`, nicht auf
  hartkodierte Keys. Eine neu hinzugefügte Frage erscheint daher automatisch
  als Profil-Kategorie und ist sofort als Regel-Bedingung wählbar.
- Profilseite zeigt die Kategorien **dynamisch** (alle aktiven Fragen nach `order`).
- Migration 0002 überführt die alten 5 festen `q_*`-Felder verlustfrei in
  `RatingAnswer` (5 Fragen mit Keys anlegen, jede Rating-Zeile → 5 Antworten).
- Migration 0004 entfernt die früheren `avg_*`-Spalten aus `TeacherScore`
  (Score-Berechnung ist nun vollständig dynamisch; nichts geht verloren, da
  alles aus `RatingAnswer` ableitbar ist).

## Regelbasiertes Achievement-System (Teil 4)
- **`AchievementRule`** definiert, unter welcher Bedingung ein Achievement
  automatisch vergeben wird: `condition_type` = `top_n_rank` (Top-N im
  Gesamt-Ranking) oder `category_score_above` (Kategorie-Score über
  Schwellenwert, verknüpft mit einer `RatingQuestion`). `duration_days` =
  null (sofort) oder X Tage **durchgängig** erfüllt.
- **`TeacherRankSnapshot`** speichert täglich Rang + Kategorie-Scores je
  Lehrkraft (für zeitbasierte Regeln).
- **Commands** (täglich per systemd-Timer):
  - `create_daily_snapshot` → erstellt den Tages-Snapshot.
  - `evaluate_achievement_rules` → wertet Regeln aus, vergibt/entzieht.
- **`manually_removed`** (an `TeacherAchievement`): Ein vom Admin manuell
  entferntes Achievement wird NICHT sofort automatisch neu vergeben, solange
  die Bedingung weiterhin erfüllt ist. Erst wenn die Bedingung einmal NICHT
  mehr erfüllt war (Streak gebrochen), wird das Flag zurückgesetzt und eine
  erneute Erfüllung kann das Achievement wieder vergeben.
- **Neue Regel anlegen:** Admin → "Regeln" → Achievement wählen →
  Bedingungstyp wählen → Schwellenwert setzen (bei `top_n_rank` = N, bei
  `category_score_above` = Mindest-Score + Frage wählen) → optional
  `duration_days` → speichern. Regeln sind über `is_active` deaktivierbar.
- **Manuelle Vergabe/Entfernung:** im Teacher-Admin über die
  "Auszeichnungen"-Inline, oder im TeacherAchievement-Admin (Aktion
  "Manuell entfernen" setzt `manually_removed=True`).

## Anti-Spam (MVP → Rate Limiting aktiv)
- Django-Auth (Login Pflicht zum Bewerten). `unique_together(pupil, teacher)` verhindert
  Mehrfachabstimmung (Update statt Duplikat).
- `core/ratelimit.py` (cache-basiert, keine extra Dependencies, HTTP 429 +
  Retry-After): Registrierung 30/h + 100/d pro IP (Schul-NAT: ganze Klasse
  meldet sich in einer Stunde an), Login 5/min + 30/h + 100/d pro IP
  (Brute-Force/Slow-Drip-Schutz), Bewerten 5/min + 30/h pro User sowie
  300/h pro IP (Klasse bewertet gemeinsam im Unterricht).
  Limits via `BAL_RATELIMITS`/`BAL_RL_*`-Env in settings.py anpassbar, Kill-Switch
  `BAL_RATELIMIT_ENABLE`. Tests in `core/tests.py` (RateLimitTests).
- Registrierung: Honeypot-Feld + E-Mail-Eindeutigkeit (erschwert Bot-Massenaccounts).
- Nginx als zweite Schicht: `limit_req` 10 r/s pro IP allgemein, 2 r/s für
  Login/Signup/Bewerten (scripts/server_setup.sh).
  Hinweis: Zähler liegen im FileBasedCache (`cache/`), der von allen
  Gunicorn-Workern geteilt wird. Für Multi-Server Redis/Memcached per
  `CACHES` konfigurieren.
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
