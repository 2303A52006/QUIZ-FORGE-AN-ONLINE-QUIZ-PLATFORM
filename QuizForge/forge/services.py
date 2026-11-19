from collections import defaultdict
from datetime import timedelta
import random
from django.db import transaction
from django.utils import timezone
from .models import Attempt, Option


def new_attempt(q, u, now):
    previous = q.attempts.filter(student=u)
    active = previous.filter(ended=None).first()
    if active:
        return active
    if not q.published or not q.opens <= now < q.closes or previous.count() >= q.limit:
        raise ValueError(
            "This quiz is unavailable or your attempt limit has been reached."
        )
    order = [
        [x.pk, list(x.options.order_by("pk").values_list("pk", flat=True))]
        for x in q.questions.order_by("pk")
    ]
    if q.shuffle_questions:
        random.shuffle(order)
    if q.shuffle_options:
        for _, opts in order:
            random.shuffle(opts)
    return Attempt.objects.create(
        quiz=q,
        student=u,
        number=previous.count() + 1,
        started=now,
        deadline=min(now + timedelta(minutes=q.minutes), q.closes),
        order=order,
    )


def finish(a, now):
    keys = set(
        Option.objects.filter(question__quiz=a.quiz, correct=True).values_list(
            "pk", flat=True
        )
    )
    right = sum(v in keys for v in a.answers.values())
    wrong = len(a.answers) - right
    a.score = max(0, right - wrong * a.quiz.penalty)
    a.ended = min(now, a.deadline)
    a.save()


@transaction.atomic
def expire(qs):
    now = timezone.now()
    for a in qs.filter(ended=None, deadline__lte=now).select_related("quiz"):
        finish(a, now)


def best(rows):
    found = {}
    for a in sorted(rows, key=lambda a: (-a.score, a.duration, a.pk)):
        found.setdefault((a.quiz_id, a.student_id), a)
    return list(found.values())


def performance(rows):
    keys = dict(
        Option.objects.filter(
            correct=True, question__quiz_id__in={a.quiz_id for a in rows}
        ).values_list("question_id", "pk")
    )
    counts = defaultdict(list)
    for a in rows:
        for q, _ in a.order:
            counts[q].append(a.answers.get(str(q)) == keys[q])
    return counts
