"""Local development settings.

One process and nothing else: ``python manage.py runserver``. Postgres and
Redis are expected to be up (both run fine as native services); a Celery
worker, a beat scheduler and a reachable mail server are not, so everything
that would otherwise need them is pointed somewhere local here.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True

# Nothing consumes the queue locally, so a dispatched task would sit in Redis
# forever — and the two that matter most are the ones a developer is most
# likely to be exercising: a confirmed payment never leaves PROCESSING because
# ``execute_payment`` is queued from ``confirm_service``, and a freshly linked
# bank never finishes its transaction scan. Running tasks inline makes the
# whole app work behind runserver alone, at the cost of the request waiting
# for the task.
CELERY_TASK_ALWAYS_EAGER = True

# Left False, unlike the test settings, which propagate deliberately. An eager
# task runs inside the request's ``transaction.on_commit`` hook, so raising
# here would turn a failed push notification into a 500 on a payment that was
# in fact created, authorised and sent. Failures are logged instead.
CELERY_TASK_EAGER_PROPAGATES = False

# Mail goes to the mailpit on this machine — SMTP on 1025, inbox at
# http://localhost:8025 — rather than the real SMTP host .env names. A dev box
# must not be able to email a customer by accident, and reading an OTP out of
# mailpit beats digging it out of a log. Set LOCAL_REAL_EMAIL=1 to use the
# .env host instead.
if not env.bool("LOCAL_REAL_EMAIL", default=False):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "localhost"
    EMAIL_PORT = 1025
    EMAIL_USE_TLS = False
    EMAIL_USE_SSL = False
    EMAIL_HOST_USER = ""
    EMAIL_HOST_PASSWORD = ""
