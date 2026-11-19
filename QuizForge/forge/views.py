import csv
from collections import Counter, defaultdict
from datetime import timedelta
from functools import wraps
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .forms import Register, Profile, Builder, Items
from .models import Quiz, Question, Option, Attempt
from .services import best, expire, finish, new_attempt, performance


def role(teacher):
    def deco(fn):
        @login_required
        @wraps(fn)
        def wrapper(r, *args, **kwargs):
            if r.user.teacher != teacher:
                raise PermissionDenied
            return fn(r, *args, **kwargs)

        return wrapper

    return deco


def page(r, t, title, **context):
    return render(r, t, dict(title=title, **context))


def home(r):
    return (
        redirect("studio")
        if r.user.is_authenticated
        else page(r, "home.html", "Overview")
    )


def register(r):
    if r.user.is_authenticated:
        return redirect("studio")
    f = Register(r.POST or None)
    if r.method == "POST" and f.is_valid():
        login(r, f.save())
        return redirect("studio")
    return page(r, "form.html", "Create student account", form=f)


@login_required
def profile(r):
    pw = r.POST.get("action") == "password"
    f = Profile(r.POST if r.method == "POST" and not pw else None, instance=r.user)
    p = PasswordChangeForm(r.user, r.POST if pw else None)
    if r.method == "POST" and (p if pw else f).is_valid():
        if pw:
            update_session_auth_hash(r, p.save())
        else:
            f.save()
        messages.success(r, "Your account has been updated.")
        return redirect("profile")
    return page(r, "form.html", "Your profile", form=f, password=p)


def rows(qs):
    expire(qs)
    return list(
        qs.exclude(ended=None)
        .select_related("quiz", "student")
        .order_by("-ended", "-pk")
    )


def mean(values):
    return round(sum(values) / len(values), 1) if values else 0


def chart(name, kind, labels, values):
    return dict(name=name, kind=kind, labels=labels, values=values)


def topics(data):
    d = defaultdict(list)
    counts = performance(data)
    for pk, topic in Question.objects.filter(pk__in=counts).values_list("pk", "topic"):
        d[topic].extend(counts[pk])
    pairs = sorted((round(100 * sum(v) / len(v), 1), k) for k, v in d.items())
    return chart(
        "Topic accuracy (%)", "bar", [k for _, k in pairs], [v for v, _ in pairs]
    )


@login_required
def studio(r):
    t = r.user.teacher
    qs = Quiz.objects.filter(owner=r.user) if t else Quiz.objects.filter(published=True)
    data = rows(
        Attempt.objects.filter(quiz__in=qs)
        if t
        else Attempt.objects.filter(student=r.user)
    )
    b = best(data)
    avg = mean([a.percentage for a in b])
    tc = topics(b)
    if t:
        stats = [
            ("Total quizzes", qs.count()),
            ("Students assessed", len({a.student_id for a in data})),
            ("Attempts", len(data)),
            ("Class average", f"{avg}%"),
        ]
        counts = Counter(timezone.localdate(a.ended) for a in data)
        days = [timezone.localdate() - timedelta(days=i) for i in reversed(range(30))]
        charts = [
            chart(
                "Attempts · last 30 days",
                "line",
                [d.strftime("%d %b") for d in days],
                [counts[d] for d in days],
            ),
            tc,
        ]
    else:
        rank = "—"
        if data:
            board = best(rows(data[0].quiz.attempts.all()))
            rank = next(i for i, a in enumerate(board, 1) if a.student_id == r.user.pk)
        stats = [
            ("Quizzes taken", len(b)),
            ("Average score", f"{avg}%"),
            ("Best score", f"{max((a.percentage for a in b),default=0):g}%"),
            ("Latest quiz rank", rank),
        ]
        charts = [
            chart(
                "Scores over time (%)",
                "line",
                [timezone.localtime(a.ended).strftime("%d %b") for a in reversed(data)],
                [a.percentage for a in reversed(data)],
            ),
            tc,
        ]
    return page(
        r,
        "studio.html",
        "Teacher studio" if t else "Student workspace",
        stats=stats,
        charts=charts,
        quizzes=qs.order_by("-opens"),
        recent=data[:8],
    )


def item_data(q):
    out = []
    for x in q.questions.order_by("pk"):
        d = dict(text=x.text, topic=x.topic, explanation=x.explanation)
        for k, o in zip("abcd", x.options.order_by("pk")):
            d[k] = o.text
            if o.correct:
                d["correct"] = k
        out.append(d)
    return out


def persist(q, items):
    q.questions.all().delete()
    for d in items:
        if not d or d.get("DELETE"):
            continue
        x = q.questions.create(**{k: d[k] for k in ("text", "topic", "explanation")})
        Option.objects.bulk_create(
            [Option(question=x, text=d[k], correct=k == d["correct"]) for k in "abcd"]
        )


@role(True)
@transaction.atomic
def build(r, pk=None):
    q = (
        get_object_or_404(Quiz, pk=pk, owner=r.user, published=False)
        if pk
        else Quiz(owner=r.user)
    )
    f = Builder(r.POST or None, instance=q)
    items = Items(r.POST or None, initial=item_data(q) if pk else [])
    if r.method == "POST":
        valid = f.is_valid()
        valid = items.is_valid() and valid
        pub = r.POST.get("action") == "publish"
        if pub and not (q.opens and q.closes):
            f.add_error(None, "Set both dates before publishing.")
            valid = False
        if valid:
            q = f.save(commit=False)
            q.published = pub
            q.save()
            persist(q, items.cleaned_data)
            messages.success(r, "Quiz published." if pub else "Draft saved.")
            return redirect("studio")
    return page(r, "build.html", "Quiz builder", form=f, items=items)


@role(True)
@require_POST
@transaction.atomic
def duplicate(r, pk):
    q = get_object_or_404(Quiz, pk=pk, owner=r.user)
    items = item_data(q)
    q.pk = None
    q.title = ("Copy of " + q.title)[:150]
    q.opens = q.closes = None
    q.published = False
    q.save()
    persist(q, items)
    return redirect("edit", q.pk)


@role(False)
@require_POST
@transaction.atomic
def start(r, pk):
    q = get_object_or_404(Quiz, pk=pk, published=True)
    expire(q.attempts.filter(student=r.user))
    try:
        a = new_attempt(q, r.user, timezone.now())
    except ValueError as e:
        messages.error(r, str(e))
        return redirect("studio")
    return redirect("take", a.pk)


@role(False)
@transaction.atomic
def take(r, pk):
    a = get_object_or_404(Attempt.objects.select_related("quiz"), pk=pk, student=r.user)
    now = timezone.now()
    ajax = r.POST.get("action") == "save"
    if not a.ended and now >= a.deadline:
        finish(a, now)

    def done():
        return (
            JsonResponse({"url": reverse("result", args=[pk])})
            if ajax
            else redirect("result", pk)
        )

    if a.ended:
        return done()
    if r.method == "POST":
        for q, opts in a.order:
            val = r.POST.get(f"q{q}")
            if val is not None:
                if val not in map(str, opts):
                    return HttpResponse("Invalid answer", status=400)
                a.answers[str(q)] = int(val)
        if ajax:
            a.save(update_fields=["answers"])
            return JsonResponse({"saved": True})
        finish(a, now)
        return done()
    texts = dict(a.quiz.questions.values_list("pk", "text"))
    opts = dict(Option.objects.filter(question__quiz=a.quiz).values_list("pk", "text"))
    items = [
        (q, texts[q], [(o, opts[o], a.answers.get(str(q)) == o) for o in ids])
        for q, ids in a.order
    ]
    return page(
        r,
        "take.html",
        a.quiz.title,
        a=a,
        items=items,
        remaining=max(0, (a.deadline - now).total_seconds()),
    )


@login_required
def result(r, pk):
    a = get_object_or_404(Attempt, pk=pk)
    if not (r.user == a.student or (r.user.teacher and a.quiz.owner == r.user)):
        raise PermissionDenied
    history = rows(a.quiz.attempts.filter(student=a.student))
    a.refresh_from_db()
    if not a.ended:
        return redirect("take", pk) if not r.user.teacher else redirect("studio")
    questions = {q.pk: q for q in a.quiz.questions.prefetch_related("options")}
    review = []
    for q, _ in a.order:
        x = questions[q]
        opts = list(x.options.all())
        selected = next((o for o in opts if o.pk == a.answers.get(str(q))), None)
        review.append((x, selected, next(o for o in opts if o.correct)))
    return page(r, "result.html", "Attempt review", a=a, history=history, review=review)


@login_required
def board(r, pk):
    q = get_object_or_404(
        Quiz, pk=pk, **({"owner": r.user} if r.user.teacher else {"published": True})
    )
    return page(
        r, "board.html", "Leaderboard", quiz=q, board=best(rows(q.attempts.all()))
    )


@role(True)
def analytics(r, pk):
    q = get_object_or_404(Quiz, pk=pk, owner=r.user)
    b = best(rows(q.attempts.all()))
    p = [a.percentage for a in b]
    cs = performance(b)
    questions = list(q.questions.order_by("pk"))
    h = [0] * 5
    for v in p:
        h[min(int(v // 20), 4)] += 1
    ch = [
        chart(
            "Score distribution",
            "bar",
            ["0–<20", "20–<40", "40–<60", "60–<80", "80–100"],
            h,
        ),
        chart(
            "Correct per question (%)",
            "bar",
            [f"Q{i}" for i in range(1, len(questions) + 1)],
            [round(100 * sum(cs[x.pk]) / len(b), 1) if b else 0 for x in questions],
        ),
        topics(b),
    ]
    stats = [
        ("Average", mean(p)),
        ("Highest", max(p, default=0)),
        ("Lowest", min(p, default=0)),
        ("Pass rate", mean([100 * a.passed for a in b])),
    ]
    return page(
        r,
        "analytics.html",
        "Quiz insights",
        quiz=q,
        stats=[(k, f"{v}%") for k, v in stats],
        charts=ch,
        questions=questions,
    )


@role(True)
def export(r, pk):
    q = get_object_or_404(Quiz, pk=pk, owner=r.user)
    data = rows(q.attempts.all())
    resp = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="quiz-{pk}.csv"'},
    )
    w = csv.writer(resp)
    w.writerow(["Student", "Attempt", "Score", "Percentage", "Passed", "Seconds"])
    for a in data:
        w.writerow(
            [
                (
                    "'" + a.student.username
                    if a.student.username[:1] in "=+-@"
                    else a.student.username
                ),
                a.number,
                a.score,
                a.percentage,
                a.passed,
                a.duration,
            ]
        )
    return resp
