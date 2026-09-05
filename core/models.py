from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils.text import slugify


class Subject(models.Model):
    """Ein Unterrichtsfach (z.B. Mathematik, Englisch)."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True, blank=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Teacher(models.Model):
    """Eine Lehrkraft mit Profil und Fächern."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    subjects = models.ManyToManyField(Subject, related_name='teachers', blank=True)
    photo = models.ImageField(upload_to='teachers/', blank=True, null=True)
    bio = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)
            slug = base
            counter = 1
            while Teacher.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class RatingQuestion(models.Model):
    """Eine Bewertungsfrage (dynamisch im Admin verwaltbar).

    Inaktive Fragen werden nicht mehr für neue Bewertungen angeboten,
    bestehende Antworten bleiben für die Score-Historie erhalten.
    ``key`` ist ein optionaler stabiler Bezeichner (z.B. 'fairness'), um
    bestimmte Fragen für Kategorie-Scores/Achievements zuordnen zu können.
    """

    text = models.CharField(max_length=200)
    key = models.CharField(max_length=50, blank=True, null=True, unique=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.text


class Rating(models.Model):
    """Eine Bewertung eines Schülers für eine Lehrkraft.

    Besteht aus mehreren Antworten (RatingAnswer), eine pro aktiver Frage
    zum Zeitpunkt der Bewertung.
    """

    pupil = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ratings'
    )
    teacher = models.ForeignKey(
        Teacher, on_delete=models.CASCADE, related_name='ratings'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Ein Schüler kann jede Lehrkraft nur einmal bewerten (Update statt Duplikat)
        constraints = [
            models.UniqueConstraint(
                fields=['pupil', 'teacher'], name='unique_pupil_teacher_rating'
            )
        ]
        ordering = ['-updated_at']

    @property
    def overall(self):
        """Gesamtscore dieser einen Bewertung (Durchschnitt aller Antworten)."""
        values = list(self.answers.values_list('value', flat=True))
        if not values:
            return 0.0
        return sum(values) / len(values)

    def __str__(self):
        return f'{self.pupil} → {self.teacher}'


class RatingAnswer(models.Model):
    """Eine einzelne Antwort (Wert 1–10) einer Bewertung auf eine Frage."""

    SCALE_MIN = 1
    SCALE_MAX = 10

    rating = models.ForeignKey(
        Rating, on_delete=models.CASCADE, related_name='answers'
    )
    question = models.ForeignKey(
        RatingQuestion, on_delete=models.CASCADE, related_name='answers'
    )
    value = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['rating', 'question'], name='unique_rating_question_answer'
            )
        ]
        ordering = ['question__order']

    def clean(self):
        from django.core.exceptions import ValidationError

        if not (self.SCALE_MIN <= self.value <= self.SCALE_MAX):
            raise ValidationError(
                f'Muss zwischen {self.SCALE_MIN} und {self.SCALE_MAX} liegen.'
            )

    def __str__(self):
        return f'{self.rating}: {self.question} = {self.value}'


class TeacherScore(models.Model):
    """Aggregierte, zwischengespeicherte Scores einer Lehrkraft.

    Werden bei jeder Neuberechnung aktualisiert, damit Ranking/Achievements
    schnell abfragbar sind (keine Live-Aggregation über alle Ratings).
    """

    teacher = models.OneToOneField(Teacher, on_delete=models.CASCADE, related_name='score')
    rating_count = models.PositiveIntegerField(default=0)
    avg_interest = models.FloatField(default=0)
    avg_productivity = models.FloatField(default=0)
    avg_fairness = models.FloatField(default=0)
    avg_atmosphere = models.FloatField(default=0)
    avg_digitalization = models.FloatField(default=0)
    avg_overall = models.FloatField(default=0)
    rank = models.PositiveIntegerField(null=True, blank=True)
    previous_rank = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['rank']

    def __str__(self):
        return f'{self.teacher}: {self.avg_overall:.1f} (Rang {self.rank})'


class Achievement(models.Model):
    """Definition einer Auszeichnung (erweiterbar, nicht im Template hartkodiert)."""

    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=20, blank=True, default='🏆')
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order']

    def __str__(self):
        return self.name


class TeacherAchievement(models.Model):
    """Verknüpfung: Lehrkraft hält/hat eine Auszeichnung gehalten."""

    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='achievements')
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE, related_name='holders')
    awarded_at = models.DateTimeField(auto_now_add=True)
    is_current = models.BooleanField(default=True)
    # Wird beim manuellen Entfernen durch den Admin gesetzt. Unterdrückt die
    # automatische Neuvergabe, bis die Bedingung erneut erfüllt wird
    # (d.h. zuerst nicht mehr, dann wieder erfüllt).
    manually_removed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('teacher', 'achievement')

    def __str__(self):
        return f'{self.teacher} – {self.achievement}'


class AchievementRule(models.Model):
    """Regelbasierte automatische Vergabe eines Achievements."""

    class ConditionType(models.TextChoices):
        TOP_N_RANK = 'top_n_rank', 'Top-N im Gesamt-Ranking'
        CATEGORY_SCORE_ABOVE = 'category_score_above', 'Kategorie-Score über Schwellenwert'

    achievement = models.ForeignKey(
        Achievement, on_delete=models.CASCADE, related_name='rules'
    )
    condition_type = models.CharField(
        max_length=30, choices=ConditionType.choices
    )
    # Bei TOP_N_RANK: N (z.B. 3). Bei CATEGORY_SCORE_ABOVE: Mindest-Score (z.B. 8.5).
    threshold_value = models.FloatField(default=0)
    # Nur bei CATEGORY_SCORE_ABOVE relevant: auf welche Frage sich der Score bezieht.
    question = models.ForeignKey(
        RatingQuestion, on_delete=models.CASCADE,
        null=True, blank=True, related_name='rules',
    )
    # null = sofort bei Erfüllung; sonst Anzahl Tage durchgängig erfüllt.
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.achievement} ({self.get_condition_type_display()})'


class TeacherRankSnapshot(models.Model):
    """Täglicher Snapshot (Rang + Score + Kategorie-Scores) je Lehrkraft.

    Dient der Auswertung zeitbasierter Regeln ('durchgängig erfüllt über X
    Tage'). Wird vom Management-Command create_daily_snapshot erzeugt.
    """

    teacher = models.ForeignKey(
        Teacher, on_delete=models.CASCADE, related_name='snapshots'
    )
    date = models.DateField()
    rank = models.PositiveIntegerField(null=True, blank=True)
    score = models.FloatField(default=0)
    # {question_key: avg} für die Kategorie-Scores des Tages
    category_scores = models.JSONField(default=dict)

    class Meta:
        unique_together = ('teacher', 'date')
        ordering = ['teacher', '-date']

    def __str__(self):
        return f'{self.teacher} @ {self.date}: Rang {self.rank}'
