from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import FIELD_ENCRYPTION_KEYS, env

DEBUG = False

# Provider secrets are encrypted with these keys (E1-S6). Shipping the dev
# fallback to production would make the ciphertext readable by anyone with
# the source, so refuse to boot without a real one.
if not env.list("FIELD_ENCRYPTION_KEYS", default=[]):
    raise ImproperlyConfigured(
        "FIELD_ENCRYPTION_KEYS must be set in production; the development "
        "fallback key is not safe for real provider secrets."
    )
