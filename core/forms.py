import time

from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core import signing

from .models import Rating, RatingAnswer, RatingQuestion

RATING_CHOICES = [(i, str(i)) for i in range(1, 11)]


# Fake-/Wegwerf-Domains: mit diesen Mails kann man sich nicht registrieren.
# (Der Bot nutzte @example.com.) Per BAL_BLOCKED_EMAIL_DOMAINS erweiterbar.
FAKE_EMAIL_DOMAINS = {
    'example.com', 'example.net', 'example.org', 'test.com',
    'mailinator.com', 'mailinator.net', 'guerrillamail.com',
    'guerrillamail.net', 'guerrillamail.org', 'guerrillamail.biz',
    '10minutemail.com', '10minutemail.net', 'tempmail.com',
    'temp-mail.org', 'temp-mail.io', 'yopmail.com', 'yopmail.net',
    'trashmail.com', 'trashmail.net', 'sharklasers.com',
    'dispostable.com', 'throwawaymail.com', 'fakeinbox.com',
    'maildrop.cc', 'harakirimail.com', 'mailnesia.com',
    'mintemail.com', 'mytrashmail.com', 'spamgourmet.com',
    'getnada.com', 'emailondeck.com', 'mohmal.com', 'tmail.ws',
    'emailfake.com', 'fakemail.net', 'inboxkitten.com',
    'tempinbox.com', 'moakt.com', 'disposablemail.com',
    'wegwerfmail.de', 'trash-mail.de', 'wegwerfadresse.com',
}

# Zeitfalle: Formular muss mindestens so lange offen gewesen sein (Bots
# feuern GET → POST in Millisekunden, Menschen brauchen Sekunden).
SIGNUP_MIN_SECONDS = 4
SIGNUP_MAX_SECONDS = 7200  # 2h, danach ist das Formular abgelaufen
_signup_signer = signing.TimestampSigner(salt='bal-signup')


def blocked_email_domains():
    extra = getattr(settings, 'BAL_BLOCKED_EMAIL_DOMAINS', '') or ''
    if isinstance(extra, str):
        extra = {d.strip().lower() for d in extra.split(',') if d.strip()}
    return FAKE_EMAIL_DOMAINS | set(extra)


class UserSignupForm(UserCreationForm):
    email = forms.EmailField(required=True)
    # Honeypot gegen dumme Bots: für Menschen unsichtbar (CSS), Bots füllen
    # jedes Feld aus → Registrierung wird still abgelehnt.
    website = forms.CharField(
        required=False, widget=forms.HiddenInput, label=""
    )
    # Zeitfalle (signed, fälschungssicher): wann wurde das Formular geladen.
    ts = forms.CharField(required=False, widget=forms.HiddenInput, label='')

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields['ts'].initial = _signup_signer.sign('signup')

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        domain = email.rsplit('@', 1)[-1].lower() if '@' in email else ''
        if domain in blocked_email_domains():
            raise forms.ValidationError(
                'Bitte eine echte E-Mail-Adresse verwenden.'
            )
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'Diese E-Mail-Adresse ist bereits registriert.'
            )
        return email

    def clean_ts(self):
        value = self.cleaned_data.get('ts') or ''
        try:
            _signup_signer.unsign(value, max_age=SIGNUP_MAX_SECONDS)
        except signing.SignatureExpired:
            raise forms.ValidationError(
                'Formular abgelaufen – bitte Seite neu laden.'
            )
        except signing.BadSignature:
            raise forms.ValidationError('Ungültige Anfrage.')
        try:
            # TimestampSigner hängt base62-kodierte Unixzeit an: v:ts:sig
            issued = signing.b62_decode(value.split(':')[-2])
        except (ValueError, IndexError):
            raise forms.ValidationError('Ungültige Anfrage.')
        if time.time() - issued < SIGNUP_MIN_SECONDS:
            raise forms.ValidationError(
                'Zu schnell – bitte Formular erneut absenden.'
            )
        return value

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('Spam erkannt.')
        return ''

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
