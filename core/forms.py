from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Rating

RATING_CHOICES = [(i, str(i)) for i in range(Rating.SCALE_MIN, Rating.SCALE_MAX + 1)]


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


class RatingForm(forms.ModelForm):
    """Bewertungsformular mit 5 Slider-Fragen (1–10)."""

    q_interest = forms.ChoiceField(
        choices=RATING_CHOICES,
        widget=forms.NumberInput(attrs={'type': 'range', 'min': 1, 'max': 10, 'value': 5}),
        label='Wie interessant ist der Unterricht?',
    )
    q_productivity = forms.ChoiceField(
        choices=RATING_CHOICES,
        widget=forms.NumberInput(attrs={'type': 'range', 'min': 1, 'max': 10, 'value': 5}),
        label='Wie produktiv ist der Unterricht?',
    )
    q_fairness = forms.ChoiceField(
        choices=RATING_CHOICES,
        widget=forms.NumberInput(attrs={'type': 'range', 'min': 1, 'max': 10, 'value': 5}),
        label='Wie fair bewertet die Lehrkraft?',
    )
    q_atmosphere = forms.ChoiceField(
        choices=RATING_CHOICES,
        widget=forms.NumberInput(attrs={'type': 'range', 'min': 1, 'max': 10, 'value': 5}),
        label='Wie ist die Arbeitsatmosphäre?',
    )
    q_digitalization = forms.ChoiceField(
        choices=RATING_CHOICES,
        widget=forms.NumberInput(attrs={'type': 'range', 'min': 1, 'max': 10, 'value': 5}),
        label='Wie ist die Digitalisierung im Unterricht?',
    )

    class Meta:
        model = Rating
        fields = [
            'q_interest', 'q_productivity', 'q_fairness',
            'q_atmosphere', 'q_digitalization',
        ]
