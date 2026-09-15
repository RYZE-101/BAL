from io import BytesIO

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone
from PIL import Image

from . import services
from .forms import RatingForm
from .images import MAX_DIMENSION, compress_image
from .models import (
    Achievement,
    AchievementRule,
    Rating,
    RatingAnswer,
    RatingQuestion,
    Subject,
    Teacher,
    TeacherAchievement,
    TeacherRankSnapshot,
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
        q_interest = RatingQuestion.objects.get(key='interest').pk
        q_productivity = RatingQuestion.objects.get(key='productivity').pk
        self.assertEqual(services.category_score(self.teacher.pk, q_interest), 6.0)
        self.assertEqual(services.category_score(self.teacher.pk, q_productivity), 8.0)
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
        self.assertEqual(services.category_score(self.teacher.pk, q.pk), 5.0)

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


class AchievementRuleTests(TestCase):
    """Regelbasiertes Achievement-System (inkl. zeitbasierter Regeln)."""

    def setUp(self):
        self.t1 = Teacher.objects.create(name='T1')
        self.t2 = Teacher.objects.create(name='T2')
        self.ach = Achievement.objects.create(slug='top-3-rule', name='Top 3')
        self.pupil = User.objects.create_user('rp', password='x')
        TeacherScore.objects.create(
            teacher=self.t1, rating_count=1, avg_overall=9, rank=1
        )
        TeacherScore.objects.create(
            teacher=self.t2, rating_count=1, avg_overall=5, rank=2
        )

    def _top_n_rule(self, n=2, days=None):
        return AchievementRule.objects.create(
            achievement=self.ach, condition_type='top_n_rank',
            threshold_value=n, duration_days=days, is_active=True,
        )

    def test_top_n_rank_immediate_award(self):
        self._top_n_rule(2)
        services.evaluate_achievement_rules()
        self.assertTrue(TeacherAchievement.objects.filter(
            teacher=self.t1, achievement=self.ach, is_current=True).exists())
        self.assertTrue(TeacherAchievement.objects.filter(
            teacher=self.t2, achievement=self.ach, is_current=True).exists())

    def test_no_double_award(self):
        self._top_n_rule(2)
        services.evaluate_achievement_rules()
        services.evaluate_achievement_rules()
        self.assertEqual(
            TeacherAchievement.objects.filter(achievement=self.ach).count(), 2)

    def test_manual_removal_suppressed_until_break(self):
        self._top_n_rule(2)
        services.evaluate_achievement_rules()
        ta = TeacherAchievement.objects.get(teacher=self.t1, achievement=self.ach)
        # Admin entfernt manuell
        ta.is_current = False
        ta.manually_removed = True
        ta.save()
        # Bedingung weiterhin erfüllt -> KEINE Neuvergabe
        services.evaluate_achievement_rules()
        ta.refresh_from_db()
        self.assertFalse(ta.is_current)
        # Bedingung bricht (t1 rutscht auf Rang 3)
        TeacherScore.objects.filter(teacher=self.t1).update(rank=3)
        services.evaluate_achievement_rules()
        ta.refresh_from_db()
        self.assertFalse(ta.manually_removed)  # Streak gebrochen
        # wieder erfüllt -> Neuvergabe
        TeacherScore.objects.filter(teacher=self.t1).update(rank=1)
        services.evaluate_achievement_rules()
        ta.refresh_from_db()
        self.assertTrue(ta.is_current)

    def test_duration_rule_needs_all_days(self):
        self._top_n_rule(1, days=3)
        today = timezone.localdate()
        # nur 2 von 3 Tagen erfüllt -> keine Vergabe
        for i in (1, 2):
            TeacherRankSnapshot.objects.create(
                teacher=self.t1, date=today - timedelta(days=i), rank=1, score=9)
        services.evaluate_achievement_rules()
        self.assertFalse(TeacherAchievement.objects.filter(
            teacher=self.t1, achievement=self.ach).exists())
        # alle 3 Tage erfüllt -> Vergabe
        TeacherRankSnapshot.objects.create(
            teacher=self.t1, date=today, rank=1, score=9)
        services.evaluate_achievement_rules()
        self.assertTrue(TeacherAchievement.objects.filter(
            teacher=self.t1, achievement=self.ach, is_current=True).exists())

    def test_category_score_rule_above_threshold(self):
        """Backward-Compat: Regel auf einer der 5 Originalfragen funktioniert
        dynamisch (ohne avg_*-Spalten)."""
        q = RatingQuestion.objects.get(key='fairness')
        AchievementRule.objects.create(
            achievement=self.ach, condition_type='category_score_above',
            threshold_value=8.5, question=q, duration_days=None, is_active=True)
        r = Rating.objects.create(pupil=self.pupil, teacher=self.t1)
        RatingAnswer.objects.create(rating=r, question=q, value=9)
        services.recompute_all_scores()
        services.update_ranking()
        services.evaluate_achievement_rules()
        self.assertTrue(TeacherAchievement.objects.filter(
            teacher=self.t1, achievement=self.ach, is_current=True).exists())

    def test_category_score_rule_below_threshold(self):
        """CATEGORY_SCORE_BELOW: Score unter Schwellenwert -> Vergabe;
        Score darüber und fehlende Werte -> keine Vergabe."""
        q = RatingQuestion.objects.get(key='fairness')
        AchievementRule.objects.create(
            achievement=self.ach, condition_type='category_score_below',
            threshold_value=5, question=q, duration_days=None, is_active=True)
        r1 = Rating.objects.create(pupil=self.pupil, teacher=self.t1)
        RatingAnswer.objects.create(rating=r1, question=q, value=3)
        r2 = Rating.objects.create(pupil=self.pupil, teacher=self.t2)
        RatingAnswer.objects.create(rating=r2, question=q, value=8)
        services.recompute_all_scores()
        services.update_ranking()
        services.evaluate_achievement_rules()
        self.assertTrue(TeacherAchievement.objects.filter(
            teacher=self.t1, achievement=self.ach, is_current=True).exists())
        self.assertFalse(TeacherAchievement.objects.filter(
            teacher=self.t2, achievement=self.ach).exists())
        # t3 ohne Bewertung für die Frage bekommt nichts (keine Daten != schlecht)
        t3 = Teacher.objects.create(name='T3')
        TeacherScore.objects.create(
            teacher=t3, rating_count=1, avg_overall=7, rank=3)
        services.evaluate_achievement_rules()
        self.assertFalse(TeacherAchievement.objects.filter(
            teacher=t3, achievement=self.ach).exists())

    def test_sixth_question_rule_works(self):
        """Eine neue 6. Frage ist als CATEGORY_SCORE_ABOVE-Bedingung nutzbar."""
        q6 = RatingQuestion.objects.create(
            text='Wie modern ist das Klassenzimmer?', key='modernity',
            order=6, is_active=True)
        AchievementRule.objects.create(
            achievement=self.ach, condition_type='category_score_above',
            threshold_value=7, question=q6, duration_days=None, is_active=True)
        r = Rating.objects.create(pupil=self.pupil, teacher=self.t1)
        RatingAnswer.objects.create(rating=r, question=q6, value=8)
        services.recompute_all_scores()
        services.update_ranking()
        services.evaluate_achievement_rules()
        self.assertTrue(TeacherAchievement.objects.filter(
            teacher=self.t1, achievement=self.ach, is_current=True).exists())
        # und der Kategorie-Score ist dynamisch abrufbar
        self.assertEqual(services.category_score(self.t1.pk, q6.pk), 8.0)


class RatingDeleteRecomputeTests(TestCase):
    """Löschen eines Ratings kaskadiert RatingAnswers und berechnet den Score neu."""

    def test_delete_rating_cascades_and_recomputes_score(self):
        teacher = Teacher.objects.create(name='T')
        pupil = User.objects.create_user('p', password='x')
        RatingHelpers.rate(teacher, pupil, {
            'interest': 10, 'productivity': 10, 'fairness': 10,
            'atmosphere': 10, 'digitalization': 10})
        services.recompute_teacher_score(teacher.pk)
        score = TeacherScore.objects.get(teacher=teacher)
        self.assertEqual(score.rating_count, 1)
        self.assertEqual(score.avg_overall, 10.0)
        self.assertEqual(RatingAnswer.objects.count(), 5)

        Rating.objects.all().delete()  # auch Bulk (Admin-Bulk)
        self.assertEqual(RatingAnswer.objects.count(), 0)  # Kaskade
        score.refresh_from_db()  # post_delete-Signal hat neu berechnet
        self.assertEqual(score.rating_count, 0)
        self.assertEqual(score.avg_overall, 0)

    def test_delete_teacher_with_related_data_no_fk_error(self):
        """Löschen einer Lehrkraft mit Ratings/Achievements/Snapshots darf
        keinen FK-Fehler werfen (Signal erzeugt keine verwaiste TeacherScore)."""
        teacher = Teacher.objects.create(name='Del T')
        pupil = User.objects.create_user('dtp2', password='x')
        RatingHelpers.rate(teacher, pupil, {
            'interest': 5, 'productivity': 5, 'fairness': 5,
            'atmosphere': 5, 'digitalization': 5})
        services.recompute_teacher_score(teacher.pk)
        TeacherRankSnapshot.objects.create(
            teacher=teacher, date=timezone.localdate(), rank=1, score=5)
        ach = Achievement.objects.create(slug='dt2-ach', name='DT2')
        TeacherAchievement.objects.create(teacher=teacher, achievement=ach)

        teacher.delete()  # darf nicht werfen
        self.assertFalse(Teacher.objects.filter(pk=teacher.pk).exists())
        self.assertEqual(TeacherRankSnapshot.objects.filter(teacher_id=teacher.pk).count(), 0)
        self.assertEqual(TeacherAchievement.objects.filter(teacher_id=teacher.pk).count(), 0)
        self.assertEqual(TeacherScore.objects.filter(teacher_id=teacher.pk).count(), 0)
        self.assertEqual(Rating.objects.filter(teacher_id=teacher.pk).count(), 0)


class OriginalQuestionManageTests(TestCase):
    """Die 5 ursprünglichen Fragen werden wie jede andere Frage behandelt."""

    def test_deactivate_reactivate_original_question(self):
        q = RatingQuestion.objects.get(key='interest')
        self.assertTrue(q.is_active)
        # deaktivieren -> nicht im Formular
        q.is_active = False
        q.save()
        texts = [f.label for f in RatingForm(pupil=None, teacher=None).fields.values()]
        self.assertNotIn('Wie interessant ist der Unterricht?', texts)
        # wieder aktivieren -> erscheint wieder
        q.is_active = True
        q.save()
        texts = [f.label for f in RatingForm(pupil=None, teacher=None).fields.values()]
        self.assertIn('Wie interessant ist der Unterricht?', texts)

    def test_overall_score_is_dynamic_with_question_count(self):
        # Gesamtscore hängt nicht an 'es gibt genau 5 Fragen' fest
        teacher = Teacher.objects.create(name='Dyn')
        pupil = User.objects.create_user('dynp', password='x')
        # Nur 2 aktive Fragen -> Antworten entsprechend
        RatingQuestion.objects.exclude(key__in=['interest', 'productivity']).update(is_active=False)
        rating = Rating.objects.create(pupil=pupil, teacher=teacher)
        RatingAnswer.objects.create(rating=rating, question=RatingQuestion.objects.get(key='interest'), value=10)
        RatingAnswer.objects.create(rating=rating, question=RatingQuestion.objects.get(key='productivity'), value=4)
        self.assertEqual(rating.overall, 7.0)  # (10+4)/2, dynamisch
        score = services.recompute_teacher_score(teacher.pk)
        self.assertEqual(score.avg_overall, 7.0)


    def test_deactivating_question_excludes_it_from_score(self):
        """Option B: Deaktivieren einer Frage entfernt sie aus dem Durchschnitt."""
        teacher = Teacher.objects.create(name='Dyn2')
        pupil = User.objects.create_user('dynp2', password='x')
        RatingHelpers.rate(teacher, pupil, {
            'interest': 10, 'productivity': 2, 'fairness': 5,
            'atmosphere': 5, 'digitalization': 5})
        score = services.recompute_teacher_score(teacher.pk)
        self.assertAlmostEqual(score.avg_overall, (10 + 2 + 5 + 5 + 5) / 5, places=2)
        # 'interest' (Wert 10) deaktivieren -> Durchschnitt sinkt
        q = RatingQuestion.objects.get(key='interest')
        q.is_active = False
        q.save()
        score = services.recompute_teacher_score(teacher.pk)
        self.assertAlmostEqual(score.avg_overall, (2 + 5 + 5 + 5) / 4, places=2)
        q.is_active = True
        q.save()


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
            'achievements-TOTAL_FORMS': '0',
            'achievements-INITIAL_FORMS': '0',
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
            'achievements-TOTAL_FORMS': '0',
            'achievements-INITIAL_FORMS': '0',
        })
        self.assertNotEqual(resp.status_code, 500)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Teacher.objects.filter(name='Neue Lehrkraft').exists())


class ImageCompressionTests(TestCase):
    """Upload-Komprimierung: große Fotos werden klein (schnelle Ladezeit)."""

    def _big_png(self, name='gross.png'):
        import os
        w, h = 1200, 900  # Rauschen: ~3,2 MB als PNG, klar über 1024 px
        img = Image.frombytes('RGB', (w, h), os.urandom(w * h * 3))
        buf = BytesIO()
        img.save(buf, 'PNG')
        buf.seek(0)
        return SimpleUploadedFile(name, buf.read(), 'image/png')

    def test_compress_image_shrinks_to_capped_jpeg(self):
        uploaded = self._big_png()
        original_len = len(uploaded.read())
        uploaded.seek(0)
        out = compress_image(uploaded)
        self.assertTrue(out.name.endswith('.jpg'))
        out.seek(0)
        with Image.open(out) as im:
            self.assertEqual(im.format, 'JPEG')
            self.assertLessEqual(max(im.size), MAX_DIMENSION)
        out.seek(0)
        self.assertLess(len(out.read()), original_len // 2)

    def test_admin_upload_saves_compressed_jpeg(self):
        import os
        admin = User.objects.create_superuser('imgadmin', '', 'pass')
        client = Client()
        client.force_login(admin)
        resp = client.post('/admin/core/teacher/add/', {
            'name': 'Foto-Lehrkraft',
            'slug': '',
            'bio': '',
            'is_active': 'on',
            'photo': self._big_png(),
            'ratings-TOTAL_FORMS': '0',
            'ratings-INITIAL_FORMS': '0',
            'achievements-TOTAL_FORMS': '0',
            'achievements-INITIAL_FORMS': '0',
        })
        self.assertEqual(resp.status_code, 302)
        teacher = Teacher.objects.get(name='Foto-Lehrkraft')
        try:
            self.assertTrue(teacher.photo.name.endswith('.jpg'))
            self.assertLess(
                os.path.getsize(teacher.photo.path), 600 * 1024)
            with Image.open(teacher.photo.path) as im:
                self.assertLessEqual(max(im.size), MAX_DIMENSION)
        finally:
            if teacher.photo and os.path.isfile(teacher.photo.path):
                os.remove(teacher.photo.path)


class RateLimitTests(TestCase):
    """Bot-Schutz: Registrierung, Login und Bewerten sind ratenbegrenzt."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _aged_ts(self, age=10):
        """Signierter Zeitfallen-Wert, der vor `age` Sekunden erzeugt wurde."""
        import time as _time
        from unittest import mock as _mock
        from django.core import signing as _signing
        with _mock.patch('time.time', return_value=_time.time() - age):
            return _signing.TimestampSigner(salt='bal-signup').sign('signup')

    def _signup_data(self, username, email=None):
        return {
            'username': username,
            'email': email or f'{username}@bal-test.de',
            'password1': 'sicheres-passwort-123',
            'password2': 'sicheres-passwort-123',
            'website': '',
            'ts': self._aged_ts(),
        }

    def test_signup_blocked_after_limit(self):
        from django.test import override_settings
        limits = {'signup_ip_hour': '3/h', 'signup_ip_day': '30/d'}
        with override_settings(BAL_RATELIMITS=limits):
            for i in range(3):
                resp = Client().post('/accounts/signup/', self._signup_data(f'bot{i}'))
                self.assertEqual(resp.status_code, 302)
            resp = Client().post('/accounts/signup/', self._signup_data('bot3'))
            self.assertEqual(resp.status_code, 429)
            self.assertIn('Retry-After', resp)
            self.assertFalse(User.objects.filter(username='bot3').exists())

    def test_signup_honeypot_rejects_bots(self):
        data = self._signup_data('honeybot')
        data['website'] = 'http://spam.example'
        resp = Client().post('/accounts/signup/', data)
        self.assertEqual(resp.status_code, 200)  # Formularfehler, kein Account
        self.assertFalse(User.objects.filter(username='honeybot').exists())

    def test_signup_duplicate_email_rejected(self):
        User.objects.create_user('echt', email='dup@bal-test.de', password='x')
        resp = Client().post(
            '/accounts/signup/', self._signup_data('fake', email='dup@bal-test.de')
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='fake').exists())

    def test_login_blocked_after_limit(self):
        from django.test import override_settings
        User.objects.create_user('opfer', password='geheim-geheim')
        limits = {'login_ip_minute': '3/m', 'login_ip_hour': '30/h'}
        with override_settings(BAL_RATELIMITS=limits):
            c = Client()
            for _ in range(3):
                c.post('/accounts/login/', {'username': 'opfer', 'password': 'falsch'})
            resp = c.post('/accounts/login/', {'username': 'opfer', 'password': 'falsch'})
            self.assertEqual(resp.status_code, 429)
            self.assertIn('Retry-After', resp)

    def test_rating_blocked_after_limit(self):
        from django.test import override_settings
        pupil = User.objects.create_user('schueler', password='x')
        teachers = [Teacher.objects.create(name=f'L{i}') for i in range(3)]
        questions = list(RatingQuestion.objects.filter(is_active=True))
        limits = {
            'rating_user_minute': '2/m', 'rating_user_hour': '60/h',
            'rating_ip_hour': '200/h',
        }
        with override_settings(BAL_RATELIMITS=limits):
            c = Client()
            c.force_login(pupil)
            for t in teachers[:2]:
                data = {f'q_{q.pk}': '5' for q in questions}
                resp = c.post(f'/lehrkraefte/{t.slug}/bewerten/', data)
                self.assertEqual(resp.status_code, 302)
            data = {f'q_{q.pk}': '5' for q in questions}
            resp = c.post(f'/lehrkraefte/{teachers[2].slug}/bewerten/', data)
            self.assertEqual(resp.status_code, 429)


class SignupAntispamTests(TestCase):
    """Fake-Mails und Zeitfalle bei der Registrierung."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _aged_ts(self, age=10):
        import time as _time
        from unittest import mock as _mock
        from django.core import signing as _signing
        with _mock.patch('time.time', return_value=_time.time() - age):
            return _signing.TimestampSigner(salt='bal-signup').sign('signup')

    def _fresh_ts(self):
        from django.core import signing as _signing
        return _signing.TimestampSigner(salt='bal-signup').sign('signup')

    def _post(self, username, email, ts):
        return Client().post('/accounts/signup/', {
            'username': username, 'email': email,
            'password1': 'Xx1!sicheres-passwort', 'password2': 'Xx1!sicheres-passwort',
            'website': '', 'ts': ts,
        })

    def test_bot_domain_example_com_blocked(self):
        resp = self._post('botx', 'botx@example.com', self._aged_ts())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='botx').exists())

    def test_disposable_domain_blocked(self):
        resp = self._post('boty', 'boty@yopmail.com', self._aged_ts())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='boty').exists())

    def test_timetrap_blocks_instant_submit(self):
        # Bot feuert GET -> POST in Millisekunden
        resp = self._post('flink', 'flink@bal-test.de', self._fresh_ts())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='flink').exists())

    def test_timetrap_blocks_tampered_value(self):
        resp = self._post('fälscher', 'f@bal-test.de', 'manipuliert')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='fälscher').exists())

    def test_timetrap_blocks_missing_value(self):
        c = Client()
        resp = c.post('/accounts/signup/', {
            'username': 'ohne', 'email': 'ohne@bal-test.de',
            'password1': 'Xx1!sicheres-passwort', 'password2': 'Xx1!sicheres-passwort',
            'website': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username='ohne').exists())

    def test_human_pace_signup_works(self):
        resp = self._post('echt', 'echt@bal-test.de', self._aged_ts(age=30))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username='echt').exists())
