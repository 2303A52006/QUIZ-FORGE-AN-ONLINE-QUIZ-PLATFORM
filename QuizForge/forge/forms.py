from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, Quiz


class Register(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")


class Profile(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email")


class Builder(forms.ModelForm):
    class Meta:
        model = Quiz
        exclude = ("owner", "published")
        labels = {
            "minutes": "Time limit (minutes)",
            "limit": "Attempts per student",
            "pass_mark": "Pass mark (%)",
            "penalty": "Penalty per wrong answer",
            "opens": "Opens (IST)",
            "closes": "Closes (IST)",
        }
        widgets = {
            x: forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}
            )
            for x in ("opens", "closes")
        }

    def clean(self):
        d = super().clean()
        if (
            (d.get("minutes") or 0) < 1
            or (d.get("limit") or 0) < 1
            or not 0 <= d.get("pass_mark", 0) <= 100
            or d.get("penalty", 0) < 0
        ):
            raise forms.ValidationError(
                "Check duration, attempt limit, pass mark and penalty."
            )
        if d.get("opens") and d.get("closes") and d["opens"] >= d["closes"]:
            raise forms.ValidationError("Close time must follow open time.")
        return d


class Item(forms.Form):
    text = forms.CharField(label="Question")
    topic = forms.CharField(max_length=80)
    explanation = forms.CharField()
    a = forms.CharField(label="Option A")
    b = forms.CharField(label="Option B")
    c = forms.CharField(label="Option C")
    d = forms.CharField(label="Option D")
    correct = forms.ChoiceField(choices=[(x, x.upper()) for x in "abcd"])


Items = forms.formset_factory(
    Item, extra=0, min_num=1, validate_min=True, can_delete=True
)
