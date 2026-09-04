from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from PIL import Image

from . import services
from .models import Achievement, Rating, Teacher, TeacherScore


class ScoreCalculationTests(TestCase):
    def setUp(self):
        self.teacher = Teacher.objects.create(name='Test Lehrer')
        self.pupil1 = User.objects.create_user('p1', password='x')
        self.pupil2 = User.objects.create_user('p2', password='x')

    def _rating(self, pupil, **kwargs):
        defaults = {
            'q_interest': 5, 'q_productivity': 5, 'q_fairness': 5,
            'q_atmosphere': 5, 'q_digitalization': 5,
        }
        defaults.update(kwargs)
        return Rating.objects.create(
            pupil=pupil, teacher=self.teacher, **defaults
        )

    def test_rating_overall_is_average(self):
        r = self._rating(self.pupil1, q_interest=10, q_productivity=10,
                         q_fairness=10, q_atmosphere=10, q_digitalization=10)
        self.assertEqual(r.overall, 10.0)

    def test_unique_constraint_pupil_teacher(self):
        self._rating(self.pupil1)
        with self.assertRaises(Exception):
            self._rating(self.pupil1)

    def test_update_replaces_not_duplicates(self):
        self._rating(self.pupil1, q_interest=2)
        self.assertEqual(Rating.objects.filter(teacher=self.teacher).count(), 1)
        Rating.objects.filter(pupil=self.pupil1, teacher=self.teacher).update(q_interest=9)
        self.assertEqual(Rating.objects.filter(teacher=self.teacher).count(), 1)

    def test_recompute_teacher_score_averages(self):
        self._rating(self.pupil1, q_interest=4, q_productivity=6)
        self._rating(self.pupil2, q_interest=8, q_productivity=10)
        score = services.recompute_teacher_score(self.teacher.pk)
        self.assertEqual(score.rating_count, 2)
        self.assertEqual(score.avg_interest, 6.0)
        self.assertEqual(score.avg_productivity, 8.0)
        # fairness/atmosphäre/digitalisierung = 5 (Defaults)
        self.assertAlmostEqual(score.avg_overall, (6 + 8 + 5 + 5 + 5) / 5, places=2)

    def test_empty_teacher_scores_zero(self):
        score = services.recompute_teacher_score(self.teacher.pk)
        self.assertEqual(score.rating_count, 0)
        self.assertEqual(score.avg_overall, 0)


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


class RankingTests(TestCase):
    def setUp(self):
        self.t1 = Teacher.objects.create(name='Alpha')
        self.t2 = Teacher.objects.create(name='Beta')
        self.t3 = Teacher.objects.create(name='Gamma')
        self.p1 = User.objects.create_user('p1', password='x')
        self.p2 = User.objects.create_user('p2', password='x')

    def _rate(self, teacher, values):
        Rating.objects.create(
            pupil=self.p1, teacher=teacher,
            q_interest=values[0], q_productivity=values[1], q_fairness=values[2],
            q_atmosphere=values[3], q_digitalization=values[4],
        )

    def test_ranking_orders_by_overall(self):
        # Alpha besser als Beta
        self._rate(self.t1, [10, 10, 10, 10, 10])
        self._rate(self.t2, [2, 2, 2, 2, 2])
        services.recompute_all_scores()
        services.update_ranking()
        scores = TeacherScore.objects.filter(rating_count__gt=0).order_by('rank')
        self.assertEqual(list(scores.values_list('teacher__name', flat=True)),
                         ['Alpha', 'Beta'])

    def test_rank_delta_tracks_movement(self):
        self._rate(self.t1, [10, 10, 10, 10, 10])  # rank 1
        self._rate(self.t2, [9, 9, 9, 9, 9])       # rank 2
        services.recompute_all_scores()
        services.update_ranking()
        alpha = TeacherScore.objects.get(teacher=self.t1)
        beta = TeacherScore.objects.get(teacher=self.t2)
        self.assertEqual(alpha.rank, 1)
        self.assertEqual(beta.rank, 2)
        self.assertEqual(alpha.previous_rank, None)

        # t1 wird schlechter → rutscht auf Platz 2 (delta +1), t2 auf 1 (delta -1)
        Rating.objects.filter(teacher=self.t1).update(
            q_interest=2, q_productivity=2, q_fairness=2,
            q_atmosphere=2, q_digitalization=2,
        )
        services.recompute_all_scores()
        services.update_ranking()
        alpha.refresh_from_db()
        beta.refresh_from_db()
        self.assertEqual(alpha.rank, 2)
        self.assertEqual(alpha.previous_rank, 1)
        self.assertEqual(services.rank_delta(alpha), 1)  # Abstieg um 1
        self.assertEqual(beta.rank, 1)
        self.assertEqual(services.rank_delta(beta), -1)  # Aufstieg um 1


class AchievementTests(TestCase):
    def test_top1_awarded_to_leader(self):
        t1 = Teacher.objects.create(name='Alpha')
        t2 = Teacher.objects.create(name='Beta')
        p = User.objects.create_user('p', password='x')
        Achievement.objects.create(slug='top-1', name='Platz 1', icon='🥇')

        Rating.objects.create(pupil=p, teacher=t1, q_interest=10, q_productivity=10,
                              q_fairness=10, q_atmosphere=10, q_digitalization=10)
        Rating.objects.create(pupil=p, teacher=t2, q_interest=9, q_productivity=9,
                              q_fairness=9, q_atmosphere=9, q_digitalization=9)
        services.refresh_all()

        holder = t1.achievements.get(achievement__slug='top-1')
        self.assertTrue(holder.is_current)

        # t1 wird schlechter → Award wechselt zu t2, Historie bleibt
        Rating.objects.filter(teacher=t1).update(q_interest=2, q_productivity=2,
                                                 q_fairness=2, q_atmosphere=2,
                                                 q_digitalization=2)
        services.refresh_all()
        self.assertFalse(t1.achievements.get(achievement__slug='top-1').is_current)
        self.assertTrue(t2.achievements.get(achievement__slug='top-1').is_current)
