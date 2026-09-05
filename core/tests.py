from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from PIL import Image

from . import services
from .forms import RatingForm
from .models import (
    Achievement,
    Rating,
    RatingAnswer,
    RatingQuestion,
    Subject,
    Teacher,
    TeacherScore,
)


class RatingHelpers:
    """Erzeugt Bewertungen im neuen Schema (Rating + RatingAnswer)."""

    @staticmethod
    def rate(teacher, pupil, values):
        rating = Rating.objects.create(pupil=pupil, teacher=teacher)
        for key, value in values.items():
            q = RatingQuestion.objects.get(key=key)
            RatingAnswer.objects.create(rating=rating, question=q, value=value)
        return rating


class ScoreCalculationTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(name='Test Lehrer')
        self.pupil1 = User.objects.create_user('p1', password='x')
        self.pupil2 = User.objects.create_user('p2', password='x')

    def test_default_questions_migrated(self):
        """Migration 0002 muss die 5 Standardfragen mit Keys anlegen."""
        keys = {q.key for q in RatingQuestion.objects.all()}
        self.assertEqual(keys, {
            'interest', 'productivity', 'fairness',
            'atmosphere', 'digitalization',
        })

    def test_rating_overall_is_average_of_answers(self):
        r = RatingHelpers.rate(
            self.teacher, self.pupil1,
            {'interest': 10, 'productivity': 10, 'fairness': 10,
             'atmosphere': 10, 'digitalization': 10},
        )
        self.assertEqual(r.overall, 10.0)

    def test_unique_constraint_pupil_teacher(self):
        RatingHelpers.rate(self.teacher, self.pupil1, {'interest': 5})
        with self.assertRaises(Exception):
            Rating.objects.create(pupil=self.pupil1, teacher=self.teacher)

    def test_recompute_teacher_score_averages_answers(self):
        RatingHelpers.rate(
            self.teacher, self.pupil1,
            {'interest': 4, 'productivity': 6, 'fairness': 5,
             'atmosphere': 5, 'digitalization': 5},
        )
        RatingHelpers.rate(
            self.teacher, self.pupil2,
            {'interest': 8, 'productivity': 10, 'fairness': 5,
             'atmosphere': 5, 'digitalization': 5},
        )
        score = services.recompute_teacher_score(self.teacher.pk)
        self.assertEqual(score.rating_count, 2)
        self.assertEqual(score.avg_interest, 6.0)
        self.assertEqual(score.avg_productivity, 8.0)
        self.assertAlmostEqual(score.avg_overall, (4 + 6 + 8 + 10 + 5 * 6) / 10, places=2)

    def test_empty_teacher_scores_zero(self):
        score = services.recompute_teacher_score(self.teacher.pk)
        self.assertEqual(score.rating_count, 0)
        self.assertEqual(score.avg_overall, 0)


class RankingTests(TestCase):
    def setUp(self):
        self.t1 = Teacher.objects.create(name='Alpha')
        self.t2 = Teacher.objects.create(name='Beta')
        self.p1 = User.objects.create_user('p1', password='x')

    def test_ranking_orders_by_overall(self):
        RatingHelpers.rate(self.t1, self.p1, {
            'interest': 10, 'productivity': 10, 'fairness': 10,
            'atmosphere': 10, 'digitalization': 10})
        RatingHelpers.rate(self.t2, self.p1, {
            'interest': 2, 'productivity': 2, 'fairness': 2,
            'atmosphere': 2, 'digitalization': 2})
        services.recompute_all_scores()
        services.update_ranking()
        scores = TeacherScore.objects.filter(rating_count__gt=0).order_by('rank')
        self.assertEqual(list(scores.values_list('teacher__name', flat=True)),
                         ['Alpha', 'Beta'])

    def test_rank_delta_tracks_movement(self):
        RatingHelpers.rate(self.t1, self.p1, {
            'interest': 10, 'productivity': 10, 'fairness': 10,
            'atmosphere': 10, 'digitalization': 10})
        RatingHelpers.rate(self.t2, self.p1, {
            'interest': 9, 'productivity': 9, 'fairness': 9,
            'atmosphere': 9, 'digitalization': 9})
        services.recompute_all_scores()
        services.update_ranking()
        alpha = TeacherScore.objects.get(teacher=self.t1)
        self.assertEqual(alpha.rank, 1)
        self.assertEqual(alpha.previous_rank, None)

        Rating.objects.filter(teacher=self.t1).first().answers.update(value=2)
        services.recompute_all_scores()
        services.update_ranking()
        alpha.refresh_from_db()
        self.assertEqual(alpha.rank, 2)
        self.assertEqual(alpha.previous_rank, 1)
        self.assertEqual(services.rank_delta(alpha), 1)


class DynamicQuestionsTests(TestCase):
    """Testet das dynamische, im Admin verwaltbare Fragen-System."""

    def setUp(self):
        self.teacher = Teacher.objects.create(name='Dyn Lehrer')
        self.pupil = User.objects.create_user('pupil', password='x')

    def test_form_renders_only_active_questions_in_order(self):
        form = RatingForm(pupil=self.pupil, teacher=self.teacher)
        texts = [f.label for f in form.fields.values()]
        self.assertEqual(texts, [
            'Wie interessant ist der Unterricht?',
            'Wie produktiv ist der Unterricht?',
            'Wie fair bewertet die Lehrkraft?',
            'Wie ist die Arbeitsatmosphäre?',
            'Wie ist die Digitalisierung im Unterricht?',
        ])

    def test_inactive_question_excluded_from_form_but_history_kept(self):
        # Bewertung mit allen 5 Fragen abgeben
        RatingHelpers.rate(self.teacher, self.pupil, {'interest': 5, 'productivity': 5,
                                                      'fairness': 5, 'atmosphere': 5,
                                                      'digitalization': 5})
        # Eine Frage deaktivieren
        q = RatingQuestion.objects.get(key='fairness')
        q.is_active = False
        q.save()
        # Formular enthält sie nicht mehr
        form = RatingForm(pupil=self.pupil, teacher=self.teacher)
        self.assertNotIn('fairness', [f.label for f in form.fields.values()])
        # Historische Antwort bleibt erhalten und zählt in den Score
        self.assertTrue(RatingAnswer.objects.filter(question=q).exists())
        score = services.recompute_teacher_score(self.teacher.pk)
        self.assertEqual(score.avg_fairness, 5.0)

    def test_form_save_creates_answers(self):
        questions = list(RatingQuestion.objects.filter(is_active=True).order_by('order'))
        data = {}
        for idx, q in enumerate(questions):
            data[f'q_{q.pk}'] = str(idx + 1)
        form = RatingForm(data, pupil=self.pupil, teacher=self.teacher)
        self.assertTrue(form.is_valid(), form.errors)
        rating = form.save()
        self.assertEqual(rating.answers.count(), len(questions))
        self.assertEqual(rating.overall, sum(range(1, len(questions) + 1)) / len(questions))


class AchievementTests(TestCase):
    def test_top1_awarded_to_leader(self):
        t1 = Teacher.objects.create(name='Alpha')
        t2 = Teacher.objects.create(name='Beta')
        p = User.objects.create_user('p', password='x')
        Achievement.objects.create(slug='top-1', name='Platz 1', icon='🥇')

        RatingHelpers.rate(t1, p, {'interest': 10, 'productivity': 10, 'fairness': 10,
                                   'atmosphere': 10, 'digitalization': 10})
        RatingHelpers.rate(t2, p, {'interest': 9, 'productivity': 9, 'fairness': 9,
                                   'atmosphere': 9, 'digitalization': 9})
        services.refresh_all()

        holder = t1.achievements.get(achievement__slug='top-1')
        self.assertTrue(holder.is_current)


class TeacherSearchTests(TestCase):
    """Suche mit Fuzzy-Matching und Fächer-Filter."""

    def setUp(self):
        self.meitner = Teacher.objects.create(name='Meitner')
        self.math = Subject.objects.create(name='Mathematik')
        self.meitner.subjects.add(self.math)
        self.other = Teacher.objects.create(name='Becker')

    def _filter(self, **params):
        from django.test import RequestFactory
        from core.views import _filter_teachers
        rf = RequestFactory()
        return _filter_teachers(rf.get('/lehrkraefte/', params))

    def test_fuzzy_typo_finds_teacher(self):
        # "Meidner"/"Meithner" müssen "Meitner" trotz Tippfehler finden
        self.assertIn(self.meitner, self._filter(q='Meidner'))
        self.assertIn(self.meitner, self._filter(q='Meithner'))

    def test_case_insensitive(self):
        self.assertIn(self.meitner, self._filter(q='meitner'))

    def test_substring_search(self):
        self.assertIn(self.meitner, self._filter(q='Meit'))

    def test_subject_filter(self):
        res = self._filter(subject=str(self.math.pk))
        self.assertIn(self.meitner, res)
        self.assertNotIn(self.other, res)

    def test_search_and_subject_combined(self):
        res = self._filter(q='Becker', subject=str(self.math.pk))
        # UND-Verknüpfung: Becker lehrt Mathe nicht -> kein Treffer
        self.assertEqual(res, [])


class AdminTeacherSaveRegressionTests(TestCase):
    """Regression: Speichern einer bestehenden Lehrkraft mit Foto darf nicht
    mit 500 enden (clean_photo griff auf content_type eines ImageFieldFile zu)."""

    def setUp(self):
        self.admin = User.objects.create_superuser('admin', '', 'pass')

    def _photo_file(self):
        buf = BytesIO()
        Image.new('RGB', (50, 50), (0, 113, 227)).save(buf, 'PNG')
        buf.seek(0)
        return SimpleUploadedFile('photo.png', buf.read(), 'image/png')

    def test_save_existing_teacher_with_photo_does_not_500(self):
        teacher = Teacher.objects.create(name='Mit Foto', bio='alt')
        teacher.photo.save('photo.png', self._photo_file(), save=True)

        client = Client()
        client.force_login(self.admin)
        resp = client.post('/admin/core/teacher/%s/change/' % teacher.pk, {
            'name': 'Mit Foto',
            'slug': 'mit-foto',
            'bio': 'geändert',
            'is_active': 'on',
            'ratings-TOTAL_FORMS': '0',
            'ratings-INITIAL_FORMS': '0',
        })
        self.assertNotEqual(resp.status_code, 500)
        self.assertEqual(resp.status_code, 302)
        teacher.refresh_from_db()
        self.assertEqual(teacher.bio, 'geändert')

    def test_add_new_teacher_with_photo_ok(self):
        client = Client()
        client.force_login(self.admin)
        resp = client.post('/admin/core/teacher/add/', {
            'name': 'Neue Lehrkraft',
            'slug': '',
            'bio': '',
            'is_active': 'on',
            'photo': self._photo_file(),
            'ratings-TOTAL_FORMS': '0',
            'ratings-INITIAL_FORMS': '0',
        })
        self.assertNotEqual(resp.status_code, 500)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Teacher.objects.filter(name='Neue Lehrkraft').exists())
