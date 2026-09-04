from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Rating, RatingAnswer, RatingQuestion

RATING_CHOICES = [(i, str(i)) for i in range(1, 11)]


class UserSignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user


class RatingForm(forms.Form):
    """Bewertungsformular: rendert dynamisch alle aktiven Fragen aus der DB.

    Legt beim Speichern das Rating plus je eine Antwort (RatingAnswer) pro
    aktiver Frage an bzw. aktualisiert diese beim Bearbeiten.
    """

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.pop('instance', None)
        self.pupil = kwargs.pop('pupil', None)
        self.teacher = kwargs.pop('teacher', None)
        super().__init__(*args, **kwargs)

        self.questions = list(
            RatingQuestion.objects.filter(is_active=True).order_by('order', 'id')
        )

        existing = {}
        if self.instance is not None:
            existing = {
                a.question_id: a.value
                for a in RatingAnswer.objects.filter(rating=self.instance)
            }

        for q in self.questions:
            initial = existing.get(q.pk, 5)
            self.fields[f'q_{q.pk}'] = forms.ChoiceField(
                choices=RATING_CHOICES,
                widget=forms.NumberInput(
                    attrs={'type': 'range', 'min': 1, 'max': 10, 'value': initial}
                ),
                label=q.text,
                initial=initial,
            )

    def save(self):
        """Erstellt bzw. aktualisiert das Rating samt Antworten."""
        rating = self.instance
        if rating is None:
            rating = Rating.objects.create(
                pupil=self.pupil, teacher=self.teacher
            )

        for q in self.questions:
            value = int(self.cleaned_data[f'q_{q.pk}'])
            RatingAnswer.objects.update_or_create(
                rating=rating, question=q, defaults={'value': value}
            )

        active_ids = [q.pk for q in self.questions]
        RatingAnswer.objects.filter(rating=rating).exclude(
            question_id__in=active_ids
        ).delete()
        return rating
