from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import DEFAULT_PLAN_CODE, FIELD_ENCRYPTION_KEYS, env

DEBUG = False

# DEFAULT_PLAN_CODE is a per-environment escape hatch for the E8-S2 plan gate:
# setting it above FOUNDING grants the Standard-only 1099 report (BRD §6.2) to
# every user in the environment at once. Real entitlements arrive with E9's
# Subscription rows, so in production the only defensible value is the lowest
# tier — refuse to boot on anything else rather than silently over-entitle.
# Spelled as a literal because a settings module must not import app code;
# PlanCode.FOUNDING in apps/common/enums.py is the same string.
if DEFAULT_PLAN_CODE != "FOUNDING":
    raise ImproperlyConfigured(
        f"DEFAULT_PLAN_CODE must be FOUNDING in production; "
        f"{DEFAULT_PLAN_CODE!r} would grant plan-gated features to every "
        "user. Per-customer plans arrive with E9 (apps/billing)."
    )

# Provider secrets are encrypted with these keys (E1-S6). Shipping the dev
# fallback to production would make the ciphertext readable by anyone with
# the source, so refuse to boot without a real one.
if not env.list("FIELD_ENCRYPTION_KEYS", default=[]):
    raise ImproperlyConfigured(
        "FIELD_ENCRYPTION_KEYS must be set in production; the development "
        "fallback key is not safe for real provider secrets."
    )
