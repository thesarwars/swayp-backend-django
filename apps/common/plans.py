"""Plan entitlements (E8-S2 seam for E9).

E9 owns ``apps/billing`` — Plan, Subscription, allowances, the lot. None of it
exists yet: there is no ``apps.billing`` in LOCAL_APPS and no plan field on
``apps/users/models/user.py``. But E8-S2 has to ship a 1099 report that is
Standard-only (BRD §6.2), and a gate added after the fact is a gate that was
open in production.

So the entitlement question is answered here, behind exactly one function.
``current_plan_code`` is the ONLY thing E9 replaces — the ordering, the
comparison and every caller stay untouched.

Fail-closed by construction:

* the default is FOUNDING, the LOWEST tier, so no entitlement is ever granted
  by accident and a user with no subscription row is simply a Founding user;
* an unrecognised ``DEFAULT_PLAN_CODE`` degrades to FOUNDING rather than
  raising (which would 500 a report) or comparing as greater-than (which would
  hand every user Enterprise on a typo);
* ``has_plan_at_least`` returns False for any minimum it does not recognise.
"""

from django.conf import settings

from apps.common.enums import PlanCode

#: Ascending entitlement order. Membership is also the allow-list: a code that
#: is not in here can never satisfy a minimum and can never be a minimum.
PLAN_ORDER = (
    PlanCode.FOUNDING,
    PlanCode.STANDARD,
    PlanCode.ENTERPRISE,
)

_RANK = {code: index for index, code in enumerate(PLAN_ORDER)}


def current_plan_code(user) -> str:
    """The plan this user is on.

    THE SEAM. E9-S1 replaces this body — and nothing else — with:

        from apps.billing.models import Subscription

        subscription = (
            Subscription.objects
            .filter(account=user, status=SubscriptionStatus.ACTIVE)
            .select_related("plan")
            .first()
        )
        return subscription.plan.code if subscription else PlanCode.FOUNDING

    Until then every user is on ``settings.DEFAULT_PLAN_CODE``, which defaults
    to FOUNDING — so the 1099 gate is shut for everyone in production, and can
    be opened per-environment for a demo without touching code.
    """
    code = getattr(settings, "DEFAULT_PLAN_CODE", PlanCode.FOUNDING)

    return code if code in _RANK else PlanCode.FOUNDING


def has_plan_at_least(user, minimum) -> bool:
    """Is this user's plan ``minimum`` or better?

    The only question callers ask, so upgrading a gate later is a change to one
    argument rather than to a chain of equality checks.
    """
    if minimum not in _RANK:
        return False

    return _RANK[current_plan_code(user)] >= _RANK[minimum]
