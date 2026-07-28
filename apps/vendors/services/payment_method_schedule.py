"""Per-method lead time and initiation date (E3-S6).

Serves the bill wizard's method step (834:3867, 840:11573): given a due date,
each of a vendor's payment methods answers "when must Swayp start this for the
money to arrive on time, and can it still make it?"

All date arithmetic delegates to :mod:`apps.common.dates` — the E1-S5 rule is
that no other module does date maths on money paths.
"""

from django.utils import timezone

from apps.common.dates import (
    RAIL_LEAD_BUSINESS_DAYS,
    estimated_arrival,
    initiation_date,
)
from apps.common.enums import PaymentRail, VendorPaymentMethodType


def rail_for_method(payment_method):
    """The rail a payment on this method would travel."""
    if payment_method.method_type == VendorPaymentMethodType.NETWORK:
        return PaymentRail.NETWORK

    if payment_method.method_type == VendorPaymentMethodType.CHECK:
        return PaymentRail.CHECK

    if payment_method.method_type == VendorPaymentMethodType.ACH:
        if payment_method.supports_same_day:
            return PaymentRail.ACH_SAMEDAY

        return PaymentRail.ACH_STANDARD

    return None


def schedule_for_method(payment_method, due_date, today=None):
    """Lead time, initiation date and arrival estimate for one method.

    Returns ``None`` when the method type has no known rail, so the caller can
    omit the block rather than emit a misleading zero.
    """
    rail = rail_for_method(payment_method)

    if rail is None:
        return None

    today = today or timezone.localdate()

    initiate_by = initiation_date(due_date, rail)

    return {
        "rail": rail,
        "due_date": due_date,
        "lead_business_days": RAIL_LEAD_BUSINESS_DAYS[rail],
        "initiate_by": initiate_by,
        "estimated_arrival": estimated_arrival(initiate_by, rail),
        # False once the initiation date has passed — the wizard uses this to
        # grey out a method that can no longer land on time.
        "can_meet_due_date": initiate_by >= today,
    }
