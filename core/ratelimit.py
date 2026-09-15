"""Fixes, cache-basiertes Rate Limiting – ohne extra Dependencies.

Schützt die Bot-angreifbaren Endpunkte (Registrierung, Login, Bewerten):
Jeder Request erhöht einen Zähler im Django-Cache (Fixed Window). Wird das
Limit überschritten, antwortet die View mit HTTP 429 + Retry-After-Header.

Verwendung::

    from .ratelimit import ratelimit

    @ratelimit("signup_ip_hour", key="ip", methods=("POST",))
    @ratelimit("signup_ip_day", key="ip", methods=("POST",))
    def signup(request): ...

``limit_key`` wird zur Request-Zeit in ``settings.BAL_RATELIMITS`` nachge-
schlagen (Fallback: ``DEFAULT_LIMITS`` unten), sodass Tests per
``override_settings`` kleine Limits setzen können. Format: ``"<n>/<s|m|h|d>"``.

Hinweis: Mit dem Default-Cache (LocMem) gilt das Limit pro Gunicorn-Worker.
Für strikte, worker-übergreifende Limits im Produktivbetrieb einen geteilten
Cache (Redis/Memcached) per ``CACHES``-Setting konfigurieren. Als zweite
Schicht begrenzt Nginx per ``limit_req`` (siehe scripts/server_setup.sh).
"""

import time
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse

_PERIODS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

# Defaults, falls settings.BAL_RATELIMITS einen Schlüssel nicht definiert.
# Schul-NAT beachten: viele Schüler teilen sich eine IP → IP-Limits großzügig,
# User-Limits streng (Bots bewerten hunderte Lehrkräfte in Minuten).
DEFAULT_LIMITS = {
    "signup_ip_hour": "10/h",   # Massen-Registrierungen durch Bots
    "signup_ip_day": "30/d",
    "login_ip_minute": "10/m",  # Credential-Stuffing / Brute Force
    "login_ip_hour": "30/h",
    "rating_user_minute": "10/m",  # Bewertungs-Spam pro Account
    "rating_user_hour": "60/h",
    "rating_ip_hour": "200/h",  # grobes Netz gegen Bot-Farmen
}


def get_client_ip(request):
    """Client-IP, hinter Reverse Proxy (X-Forwarded-For) nutzbar."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def get_limit(limit_key):
    configured = getattr(settings, "BAL_RATELIMITS", {})
    return configured.get(limit_key, DEFAULT_LIMITS[limit_key])


def parse_rate(rate):
    count, _, period = rate.partition("/")
    return int(count), _PERIODS[period]


def check_limited(group, ident, rate):
    """Erhöht den Zähler, gibt (limited: bool, retry_after: int) zurück."""
    limit, window = parse_rate(rate)
    bucket = int(time.time() // window)
    key = f"bal-rl:{group}:{window}:{bucket}:{ident}"
    try:
        # add() ist atomar: nur der erste Caller setzt, alle anderen erhöhen.
        if cache.add(key, 1, timeout=window):
            count = 1
        else:
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=window)
                count = 1
    except Exception:
        return False, 0  # Cache kaputt → lieber durchlassen als Seite lahmlegen
    if count <= limit:
        return False, 0
    retry_after = (bucket + 1) * window - int(time.time()) + 1
    return True, max(retry_after, 1)


def _too_many_requests(request, retry_after):
    from django.shortcuts import render
    from django.template import TemplateDoesNotExist

    try:
        response = render(request, "429.html", status=429)
    except TemplateDoesNotExist:
        response = HttpResponse(
            "Zu viele Anfragen \u2013 bitte kurz warten und erneut versuchen.",
            status=429,
            content_type="text/plain; charset=utf-8",
        )
    response["Retry-After"] = str(retry_after)
    return response


def _key_func(key):
    if callable(key):
        return key
    if key == "user":
        def user_key(request):
            if request.user.is_authenticated:
                return f"user-{request.user.pk}"
            return f"ip-{get_client_ip(request)}"
        return user_key
    # "ip" (Default)
    return lambda request: f"ip-{get_client_ip(request)}"


def ratelimit(limit_key, key="ip", methods=("POST",)):
    """Decorator: begrenzt Requests pro Zeiteinheit, sonst HTTP 429."""
    resolve_key = _key_func(key)
    methods = set(methods)

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.method in methods and getattr(
                settings, "BAL_RATELIMIT_ENABLE", True
            ):
                limited, retry_after = check_limited(
                    limit_key, resolve_key(request), get_limit(limit_key)
                )
                if limited:
                    return _too_many_requests(request, retry_after)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
