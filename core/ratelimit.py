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

Hinweis: Der Cache (FileBasedCache, siehe settings.CACHES) wird von allen
Gunicorn-Workern geteilt. Für Multi-Server-Betrieb Redis/Memcached per
``CACHES`` konfigurieren. Als zweite Schicht begrenzt Nginx per
``limit_req`` (siehe scripts/server_setup.sh).
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
    "signup_ip_hour": "30/h",   # Massen-Registrierungen durch Bots
    "signup_ip_day": "100/d",  # grosszuegig: Schulklasse hinter einer NAT-IP
    "login_ip_minute": "5/m",  # Credential-Stuffing / Brute Force
    "login_ip_hour": "30/h",
    "login_ip_day": "100/d",   # Slow-Drip ueber Stunden hinweg
    "rating_user_minute": "5/m",  # Bewertungs-Spam pro Account
    "rating_user_hour": "30/h",
    "rating_ip_hour": "300/h",  # grobes Netz gegen Bot-Farmen, hoch wegen Schul-NAT
}


def get_client_ip(request):
    """Client-IP hinter Reverse Proxy.

    WICHTIG: Der *erste* X-Forwarded-For-Eintrag ist client-kontrolliert
    (Spoofing → Limit-Umgehung). Nginx hängt die echte Peer-IP per
    ``$proxy_add_x_forwarded_for`` hinten an, daher gilt: X-Real-IP
    (setzt Nginx auf den echten Peer, nicht fälschbar), sonst der LETZTE
    XFF-Eintrag, sonst REMOTE_ADDR.
    """
    real_ip = request.META.get("HTTP_X_REAL_IP")
    if real_ip:
        return real_ip.strip()
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def get_limit(limit_key):
    configured = getattr(settings, "BAL_RATELIMITS", {})
    return configured.get(limit_key, DEFAULT_LIMITS[limit_key])


def parse_rate(rate):
    count, _, period = rate.partition("/")
    return int(count), _PERIODS[period]


def check_limited(group, ident, rate):
    """Erhöht den Zähler.

    Gibt (limited, retry_after, count, limit) zurück. ``count``/``limit``
    landen als X-RateLimit-Header auf der Response (Debug/Monitoring).
    """
    import logging

    limit, window = parse_rate(rate)
    now = int(time.time())
    bucket = now // window
    key = f"bal-rl:{group}:{window}:{bucket}:{ident}"
    remaining_ttl = (bucket + 1) * window - now
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
            # incr() schreibt mit Default-TTL → Fenster-TTL wiederherstellen,
            # sonst würden Slow-Drip-Angriffe dem Tages-/Stundenlimit entgehen.
            try:
                cache.set(key, count, timeout=max(remaining_ttl, 1))
            except Exception:
                pass
    except Exception:
        # Cache kaputt → durchlassen, aber LAUT (sonst Fail-Open unbemerkt).
        logging.getLogger(__name__).exception(
            "Rate-Limit-Cachefehler bei %s (lasse durch)", key
        )
        return False, 0, 0, limit
    if count <= limit:
        return False, 0, count, limit
    return True, max(remaining_ttl + 1, 1), count, limit


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
                limited, retry_after, count, limit = check_limited(
                    limit_key, resolve_key(request), get_limit(limit_key)
                )
                if limited:
                    return _too_many_requests(request, retry_after)
                response = view_func(request, *args, **kwargs)
                response["X-RateLimit-Limit"] = str(limit)
                response["X-RateLimit-Remaining"] = str(max(limit - count, 0))
                return response
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
