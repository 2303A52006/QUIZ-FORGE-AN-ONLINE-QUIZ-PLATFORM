from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import User, Quiz, Attempt
from .services import finish, new_attempt, best


class QuizTests(TestCase):
    def setUp(self):
        self.t = User.objects.create(username="t", teacher=True)
        self.u = User.objects.create(username="u")
        self.now = timezone.now()
        self.q = Quiz.objects.create(
            owner=self.t,
            title="Test",
            opens=self.now - timedelta(days=1),
            closes=self.now + timedelta(hours=1),
            published=True,
            shuffle_questions=True,
            shuffle_options=True,
            penalty=Decimal(".25"),
        )
        self.x = []
        for i in range(3):
            x = self.q.questions.create(
                text=f"Question {i}", explanation="PRIVATE FEEDBACK", topic="Logic"
            )
            self.x.append(
                [x, [x.options.create(text=str(k), correct=k == 2) for k in range(4)]]
            )
        self.client.force_login(self.u)

    def start(self):
        return self.client.post(reverse("start", args=[self.q.pk]))

    def new(self):
        self.start()
        return Attempt.objects.get()

    def test_scoring_penalty_and_unanswered(self):
        a = self.new()
        x, y = self.x[:2]
        a.answers = {str(x[0].pk): x[1][2].pk, str(y[0].pk): y[1][0].pk}
        finish(a, self.now)
        self.assertEqual(a.score, Decimal(".75"))
        a.answers = {str(y[0].pk): y[1][0].pk}
        finish(a, self.now)
        self.assertEqual(a.score, 0)

    def test_full_marks(self):
        a = self.new()
        resp = self.client.post(
            reverse("take", args=[a.pk]),
            {f"q{x.pk}": opts[2].pk for x, opts in self.x},
            follow=True,
        )
        self.assertContains(resp, "Passed")
        a.refresh_from_db()
        self.assertEqual(a.score, 3)

    def test_window(self):
        for op, cl in [(1, 2), (-2, -1)]:
            self.q.opens = self.now + timedelta(days=op)
            self.q.closes = self.now + timedelta(days=cl)
            self.q.save()
            self.start()
            self.assertFalse(Attempt.objects.exists())

    def test_deadlines(self):
        self.q.closes = self.now + timedelta(seconds=10)
        self.q.save()
        a = self.new()
        self.assertEqual(a.deadline, self.q.closes)
        a.deadline = self.now - timedelta(seconds=1)
        a.save()
        x, opts = self.x[0]
        self.client.post(reverse("take", args=[a.pk]), {f"q{x.pk}": opts[2].pk})
        a.refresh_from_db()
        self.assertEqual(a.ended, a.deadline)
        self.assertEqual(a.answers, {})

    def test_expiry_on_dashboard(self):
        a = self.new()
        self.assertEqual(a.deadline - a.started, timedelta(minutes=self.q.minutes))
        a.deadline = self.now
        a.save()
        self.client.get(reverse("studio"))
        a.refresh_from_db()
        self.assertEqual(a.ended, self.now)

    def test_limit_and_resume(self):
        a = self.new()
        self.start()
        self.assertEqual(Attempt.objects.count(), 1)
        finish(a, self.now)
        self.start()
        self.assertEqual(Attempt.objects.count(), 1)

    def test_order_and_autosave(self):
        a = self.new()
        url = reverse("take", args=[a.pk])
        first = self.client.get(url)
        self.assertNotContains(first, "PRIVATE FEEDBACK")
        q, ids = a.order[0]
        self.client.post(url, {"action": "save", f"q{q}": ids[-1]})
        second = self.client.get(url)
        self.assertEqual(
            [[q, [v for v, _, _ in opts]] for q, _, opts in second.context["items"]],
            a.order,
        )
        self.assertContains(second, "checked")
        a.refresh_from_db()
        self.assertEqual(a.answers[str(q)], ids[-1])
        self.assertEqual(
            self.client.post(url, {"action": "save", f"q{q}": -1}).status_code, 400
        )

    def test_permissions(self):
        a = self.new()
        self.assertEqual(self.client.get(reverse("build")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("csv", args=[self.q.pk])).status_code, 403
        )
        other = User.objects.create(username="other", teacher=True)
        self.client.force_login(other)
        for name in ["analytics", "board", "csv", "edit", "duplicate"]:
            self.assertEqual(
                self.client.post(reverse(name, args=[self.q.pk])).status_code, 404
            )
        self.assertEqual(
            self.client.get(reverse("result", args=[a.pk])).status_code, 403
        )
        self.assertEqual(self.start().status_code, 403)
        self.client.force_login(User.objects.create(username="student2"))
        self.assertEqual(self.client.get(reverse("take", args=[a.pk])).status_code, 404)

    def test_best_tie(self):
        self.q.limit = 3
        self.q.save()
        a = self.new()
        finish(a, a.started + timedelta(minutes=5))
        b = new_attempt(self.q, self.u, self.now)
        finish(b, self.now + timedelta(minutes=1))
        self.assertEqual(best([a, b]), [b])
        a.score = 1
        self.assertEqual(best([b, a]), [a])

    def test_teacher_workflow(self):
        a = self.new()
        finish(a, self.now)
        self.client.force_login(self.t)
        for name in ["analytics", "board", "csv"]:
            self.assertEqual(
                self.client.get(reverse(name, args=[self.q.pk])).status_code, 200
            )
        self.assertContains(self.client.get(reverse("studio")), "Teacher studio")
        resp = self.client.post(reverse("duplicate", args=[self.q.pk]), follow=True)
        self.assertContains(resp, "Copy of Test")
        copy = Quiz.objects.exclude(pk=self.q.pk).get()
        self.assertIsNone(copy.opens)
        self.assertFalse(copy.published)
        self.assertEqual(copy.questions.count(), 3)

    def test_publish(self):
        self.client.force_login(self.t)
        fields = {
            "title": "Published test",
            "minutes": 2,
            "limit": 1,
            "penalty": 0,
            "pass_mark": 60,
            "opens": "2026-01-01T09:00",
            "closes": "2026-12-31T12:00",
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
        }
        fields.update(
            {
                "form-0-" + k: v
                for k, v in dict(
                    text="What?",
                    topic="Topic",
                    explanation="Because.",
                    a="A",
                    b="B",
                    c="C",
                    d="D",
                    correct="c",
                ).items()
            }
        )
        fields["action"] = "publish"
        self.client.post(reverse("build"), fields)
        q = Quiz.objects.get(title="Published test")
        self.assertTrue(q.published)
        self.assertEqual(q.questions.get().options.get(correct=True).text, "C")
        self.assertEqual(self.client.get(reverse("edit", args=[q.pk])).status_code, 404)

    def test_public_pages(self):
        self.client.logout()
        for name in ["home", "login", "register"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.get(reverse("studio")).status_code, 302)
