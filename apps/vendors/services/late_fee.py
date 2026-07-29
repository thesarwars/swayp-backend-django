"""Vendor late-fee policy arithmetic (E3-S1 fields; used by E6-S6 and E8-S4).

Calendar days, deliberately, and that is this module's reading of the epic's
"late-fee math via date engine": a late fee is a contractual term on the
vendor's calendar, so a grace period that expires on Veterans Day expires on
Veterans Day. The business-day helpers in apps/common/dates.py model banking
transit, which is a different question. What this module does take from the
date engine is whose day it is — ``today_eastern`` — because the alternative,
``timezone.localdate()``, answers in UTC and turns the last day of grace into
the first day of the fee at 20:00 Eastern.
"""

import datetime as dt

from apps.common.dates import today_eastern


def has_late_fee_policy(vendor):
    """A policy exists only when there is a fee worth warning about."""
    return (
        vendor is not None
        and vendor.late_fee_amount is not None
        and vendor.late_fee_amount > 0
    )


def grace_days(vendor):
    """Grace days for a vendor with a policy, else None.

    ``late_fee_grace_days`` is independently nullable
    (apps/vendors/models/vendor.py:63-66); a fee with no stated grace applies
    from the day after the due date.
    """
    if not has_late_fee_policy(vendor):
        return None

    return vendor.late_fee_grace_days or 0


def days_until_late_fee(*, due_date, vendor, today=None):
    """``(due_date + grace_days) - today`` in calendar days; None if no policy.

    Negative once the fee has already applied — callers decide whether that is
    still worth saying. Algebraically identical to E6-S6's
    ``grace_days - days_overdue``, which is why both go through this module.
    """
    days = grace_days(vendor)

    if days is None:
        return None

    today = today or today_eastern()

    return (due_date + dt.timedelta(days=days) - today).days
