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


class Rating(models.Model):
    """Eine Bewertung eines Schülers für eine Lehrkraft (5 Fragen, Skala 1–10)."""

    SCALE_MIN = 1
    SCALE_MAX = 10

    pupil = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ratings'
    )
    teacher = models.ForeignKey(
        Teacher, on_delete=models.CASCADE, related_name='ratings'
    )
    # 5 Kategorien
    q_interest = models.PositiveSmallIntegerField()       # Wie interessant?
    q_productivity = models.PositiveSmallIntegerField()   # Wie produktiv?
    q_fairness = models.PositiveSmallIntegerField()       # Wie fair?
    q_atmosphere = models.PositiveSmallIntegerField()     # Arbeitsatmosphäre
    q_digitalization = models.PositiveSmallIntegerField() # Digitalisierung
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

    def clean(self):
        from django.core.exceptions import ValidationError

        for field in self.RATING_FIELDS:
            value = getattr(self, field)
            if value is not None and not (self.SCALE_MIN <= value <= self.SCALE_MAX):
                raise ValidationError(
                    {field: f'Muss zwischen {self.SCALE_MIN} und {self.SCALE_MAX} liegen.'}
                )

    @property
    def RATING_FIELDS(self):
        return [
            'q_interest', 'q_productivity', 'q_fairness',
            'q_atmosphere', 'q_digitalization',
        ]

    @property
    def overall(self):
        """Gesamtscore dieser einen Bewertung (Durchschnitt der 5 Kategorien)."""
        values = [getattr(self, f) for f in self.RATING_FIELDS]
        return sum(values) / len(values)

    def __str__(self):
        return f'{self.pupil} → {self.teacher}'


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

    class Meta:
        unique_together = ('teacher', 'achievement')

    def __str__(self):
        return f'{self.teacher} – {self.achievement}'
