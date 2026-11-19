from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    teacher = models.BooleanField(default=False)


class Quiz(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    minutes = models.PositiveIntegerField(default=15)
    pass_mark = models.PositiveIntegerField(default=50)
    penalty = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    limit = models.PositiveIntegerField(default=1)
    shuffle_questions = models.BooleanField(default=False)
    shuffle_options = models.BooleanField(default=False)
    opens = models.DateTimeField(null=True, blank=True)
    closes = models.DateTimeField(null=True, blank=True)
    published = models.BooleanField(default=False)

    @property
    def status(self):
        if not self.published:
            return "Draft"
        now = timezone.now()
        return (
            "Upcoming"
            if now < self.opens
            else "Closed" if now >= self.closes else "Open"
        )

    def __str__(self):
        return self.title


class Question(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField()
    topic = models.CharField(max_length=80)
    explanation = models.TextField()


class Option(models.Model):
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="options"
    )
    text = models.TextField()
    correct = models.BooleanField(default=False)


class Attempt(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(User, on_delete=models.CASCADE)
    number = models.PositiveIntegerField()
    started = models.DateTimeField()
    deadline = models.DateTimeField()
    ended = models.DateTimeField(null=True)
    order = models.JSONField(default=list)
    answers = models.JSONField(default=dict)
    score = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["quiz", "student", "number"], name="unique_try"
            )
        ]

    @property
    def percentage(self):
        return round(float(self.score) * 100 / len(self.order), 2)

    @property
    def passed(self):
        return self.score * 100 >= self.quiz.pass_mark * len(self.order)

    @property
    def duration(self):
        return (self.ended - self.started).total_seconds()
