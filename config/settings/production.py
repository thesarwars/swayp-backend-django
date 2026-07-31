"""Production settings.

Every unsafe default in ``base.py`` is either overridden here or turned into a
refusal to boot. That direction is deliberate: a service that will not start is
an incident someone fixes in ten minutes, whereas a service that starts with a
development secret key is an incident nobody notices until sessions are being
forged.

Nothing here has a fallback. If a value matters in production it comes from the
environment, or the process exits.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False


def _require(name, *, hint=""):
    value = env(name, default="")

    if not value:
        raise ImproperlyConfigured(
            f"{name} must be set in production." + (f" {hint}" if hint else "")
        )

    return value


def _require_list(name, *, hint=""):
    values = env.list(name, default=[])

    if not values:
        raise ImproperlyConfigured(
            f"{name} must be set in production." + (f" {hint}" if hint else "")
        )

    return values


def _flag(name, default="True"):
    return env(name, default=default).lower() in {"1", "true", "yes", "on"}


# --- secrets ---------------------------------------------------------------

# base.py ships a literal "django-insecure-…" key so a fresh checkout runs.
# That key is in the repository, so anyone who can read the source can forge a
# session cookie or a password-reset token. A missing value here has only one
# safe reading.
SECRET_KEY = _require(
    "DJANGO_SECRET_KEY",
    hint="Generate with: python -c \"from django.core.management.utils "
         "import get_random_secret_key; print(get_random_secret_key())\"",
)

if SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is the development key from base.py. Generate a "
        "real one."
    )

# Provider secrets are encrypted with these keys (E1-S6). Shipping the dev
# fallback would make the ciphertext readable by anyone with the source.
if not env.list("FIELD_ENCRYPTION_KEYS", default=[]):
    raise ImproperlyConfigured(
        "FIELD_ENCRYPTION_KEYS must be set in production; the development "
        "fallback key is not safe for real provider secrets."
    )

# --- who may reach us ------------------------------------------------------

# Empty ALLOWED_HOSTS with DEBUG=False makes Django reject every request, so
# without this the service starts and serves nothing. Naming the hosts also
# closes Host-header poisoning, which is what reaches into reset links.
ALLOWED_HOSTS = _require_list(
    "DJANGO_ALLOWED_HOSTS",
    hint="Comma-separated, e.g. api.getswayp.com",
)

# The frontend is a separate origin, so without this every browser call fails
# CORS and the API looks broken from outside while passing every test.
# Explicit origins rather than CORS_ALLOW_ALL_ORIGINS: this API carries a
# bearer token and moves money, and a wildcard is not a policy.
CORS_ALLOWED_ORIGINS = _require_list(
    "CORS_ALLOWED_ORIGINS",
    hint="Comma-separated scheme+host, e.g. https://app.getswayp.com",
)
CORS_ALLOW_CREDENTIALS = True

# Derived from the CORS list so the two cannot drift apart.
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

# --- transport -------------------------------------------------------------

# Behind a load balancer that terminates TLS, Django sees plain HTTP and would
# redirect forever without being told how the balancer reports the scheme.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = _flag("DJANGO_SECURE_SSL_REDIRECT")

# The health probes must answer over plain HTTP. Docker's HEALTHCHECK, a load
# balancer's target check and a k8s probe all connect to the container directly
# — no proxy, so no X-Forwarded-Proto, so the redirect fires and they get a 301
# instead of the app.
#
# The failure mode that makes this worth a setting: `curl -f` treats 3xx as
# success, so the probe passes without ever reaching Django. The container then
# reports healthy whatever state the app is in, and a check that cannot fail is
# worse than no check — it is a check everyone believes.
#
# Exempting them costs nothing: both are unauthenticated, take no input, and
# return a fixed shape (see apps/common/api_health.py).
SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$"]

# Browsers remember HSTS and it cannot be withdrawn quickly, so this defaults
# to off. Set it to 31536000 once the domain and every subdomain are confirmed
# to serve HTTPS — not before.
SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", default="0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- entitlements ----------------------------------------------------------

# Read from the environment rather than taken from the star-import: base.py
# evaluates its module body once, so an inherited value reflects whatever the
# environment held at first import and not what this process was actually
# given.
DEFAULT_PLAN_CODE = env("DEFAULT_PLAN_CODE", default="FOUNDING")

# DEFAULT_PLAN_CODE is a per-environment escape hatch for the E8-S2 plan gate:
# setting it above FOUNDING grants the Standard-only 1099 report (BRD §6.2) to
# every user in the environment at once. Real entitlements come from E9's
# Subscription rows, so in production the only defensible value is the lowest
# tier — refuse to boot rather than silently over-entitle.
# Spelled as a literal because a settings module must not import app code;
# PlanCode.FOUNDING in apps/common/enums.py is the same string.
if DEFAULT_PLAN_CODE != "FOUNDING":
    raise ImproperlyConfigured(
        f"DEFAULT_PLAN_CODE must be FOUNDING in production; "
        f"{DEFAULT_PLAN_CODE!r} would grant plan-gated features to every "
        "user. Per-customer plans arrive with E9 (apps/billing)."
    )

# --- money -----------------------------------------------------------------

# Selecting Stripe without its keys fails at the first subscribe rather than
# at boot, which turns a configuration mistake into a customer meeting a 503
# during signup. Check it here instead.
if env("SUBSCRIPTION_BILLING_PROVIDER", default="mock") == "stripe":
    _require(
        "STRIPE_SECRET_KEY",
        hint="Or set SUBSCRIPTION_BILLING_PROVIDER=mock to run without "
             "collecting money.",
    )
    _require(
        "STRIPE_BILLING_WEBHOOK_SECRET",
        hint="From the Stripe Dashboard endpoint for "
             "/webhooks/stripe/billing/. Without it subscriptions never "
             "confirm as paid.",
    )

# Emailed invite links point here, and a link to localhost is a dead end in
# somebody's inbox. Read from env for the same reason as DEFAULT_PLAN_CODE.
FRONTEND_URL = env("FRONTEND_URL", default="")

if not FRONTEND_URL or FRONTEND_URL.startswith("http://localhost"):
    raise ImproperlyConfigured(
        "FRONTEND_URL must be set to the public frontend origin; team "
        "invitation emails would otherwise carry an unusable link."
    )

# --- logging ---------------------------------------------------------------

# With DEBUG=False Django's default logging swallows almost everything, so an
# incident leaves no trace. Everything goes to stdout, which is where a
# container platform collects it.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        # The money paths log at INFO deliberately: a fee that was not charged
        # or a guarantee that was refunded has to be reconstructable later.
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
