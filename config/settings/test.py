from .base import *  # noqa: F401,F403

# Tests never touch a real mail server.
MESSAGING_PROVIDER = "mock"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Every provider is pinned to its deterministic mock and Flo's phrasing is off,
# so a test run makes no external call by construction rather than by
# discipline. E7-S4 AC1 ("flag off -> zero external calls") is asserted on top
# of this, not assumed from it.
BANK_DATA_PROVIDER = "mock"
MONEY_MOVEMENT_PROVIDER = "mock"
DIRECTORY_PROVIDER = "mock"
CHECK_MAIL_PROVIDER = "mock"
LLM_PROVIDER = "template"
FLO_LLM_ENABLED = False
ANTHROPIC_API_KEY = ""

# Pinned for the same reason as the rest, and with a sharper edge: base.py
# reads .env, so a developer with real Stripe keys configured would otherwise
# have the whole suite create customers and subscriptions in a live account
# on every run. Slow, flaky, and it leaves real objects behind.
SUBSCRIPTION_BILLING_PROVIDER = "mock"
STRIPE_SECRET_KEY = ""
STRIPE_PUBLISHABLE_KEY = ""
STRIPE_BILLING_WEBHOOK_SECRET = "whsec_test_secret"

# The suite has to be runnable with nothing else running — no Postgres, no
# .env. An unrunnable suite is indistinguishable from no suite, and that is
# how four acceptance criteria that name a test ended up with none.
# Set TEST_USE_POSTGRES=1 to run against the real engine instead.
if not env.bool("TEST_USE_POSTGRES", default=False):  # noqa: F405
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

# Named explicitly so cache-backed behaviour (the Flo daily call cap) is
# exercised against a real backend rather than whatever the default happens
# to be, and is isolated per run.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "swayp-test-cache",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
