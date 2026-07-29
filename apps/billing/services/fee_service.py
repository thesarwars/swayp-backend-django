"""Per-transaction fees (E9-S3) and delivery-guarantee refunds (E9-S4).

BRD §6.2:

- standard ACH — free, unlimited
- same-day ACH — $4.99, **only when booked before the daily bank cutoff**;
  after cutoff same-day is not offered at all, so no charge is created
- standard check — free up to the plan allotment, then $2.99
- expedited check — $8.99 on every plan

The same-day and expedited fees buy a delivery promise. Missing it refunds
the fee automatically — that is the product commitment, not a goodwill
gesture, so it runs off the ledger rather than a support queue.
"""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import (
    FEE_AMOUNTS,
    GUARANTEED_KINDS,
    AllowanceKind,
    FeeCharge,
    FeeKind,
    FeeState,
)
from apps.billing.services.allowance_service import AllowanceService
from apps.common.dates import cutoff_datetime_et, estimated_arrival
from apps.common.enums import PaymentRail

logger = logging.getLogger(__name__)


class FeeService:

    def __init__(self):
        self.allowances = AllowanceService()

    # --- eligibility ------------------------------------------------------

    def same_day_available(self, *, now=None, send_date=None):
        """Whether same-day ACH can still be booked today.

        After the daily bank cutoff the rail cannot deliver same-day, so it is
        withdrawn rather than sold and then missed. No offer, no fee, nothing
        to refund.
        """
        now = now or timezone.now()
        send_date = send_date or timezone.localdate()

        return now <= cutoff_datetime_et(send_date)

    # --- charging ---------------------------------------------------------

    @transaction.atomic
    def charge_for_payment(self, *, subscription, payment, expedited=False,
                           now=None):
        """Create whatever fee this payment attracts, or none.

        Returns the FeeCharge or ``None``. Standard ACH is free, and a
        standard check inside the plan allotment is free too.
        """
        now = now or timezone.now()

        if payment.rail == PaymentRail.ACH_SAMEDAY:
            return self._charge_same_day(subscription, payment, now)

        if payment.rail == PaymentRail.CHECK:
            return self._charge_check(subscription, payment, expedited, now)

        # ACH_STANDARD and NETWORK carry no per-transaction fee.
        return None

    def _charge_same_day(self, subscription, payment, now):
        send_date = payment.initiated_date or timezone.localdate()

        if not self.same_day_available(now=now, send_date=send_date):
            # Booked after the cutoff: same-day was not deliverable, so it was
            # not sold. Explicitly no FeeCharge row (E9-S3 AC).
            logger.info(
                "same-day requested after cutoff for %s; no fee charged",
                payment.transaction_reference,
            )
            return None

        return self._create(
            subscription=subscription,
            payment=payment,
            kind=FeeKind.SAME_DAY_ACH,
            guaranteed_arrival=estimated_arrival(
                send_date, PaymentRail.ACH_SAMEDAY
            ),
        )

    def _charge_check(self, subscription, payment, expedited, now):
        send_date = payment.initiated_date or timezone.localdate()

        if expedited:
            # $8.99 regardless of plan or allotment — expedited is a separate
            # product, not an overage.
            return self._create(
                subscription=subscription,
                payment=payment,
                kind=FeeKind.EXPEDITED_CHECK,
                guaranteed_arrival=estimated_arrival(
                    send_date, PaymentRail.CHECK
                ),
            )

        _, is_overage = self.allowances.consume_metered(
            subscription=subscription, kind=AllowanceKind.CHECKS
        )

        if not is_overage:
            # Inside the free allotment.
            return None

        return self._create(
            subscription=subscription,
            payment=payment,
            kind=FeeKind.CHECK_OVERAGE,
            # An overage buys no speed promise, so nothing to guarantee.
            guaranteed_arrival=None,
        )

    def _create(self, *, subscription, payment, kind, guaranteed_arrival):
        try:
            with transaction.atomic():
                return FeeCharge.objects.create(
                    subscription=subscription,
                    payment=payment,
                    kind=kind,
                    amount=FEE_AMOUNTS[kind],
                    state=FeeState.PENDING,
                    guaranteed_arrival=guaranteed_arrival,
                )
        except IntegrityError:
            # uniq_fee_kind_per_payment: a retry re-entered the fee path, and
            # the customer must not be charged twice for one payment.
            logger.info(
                "fee %s already charged for %s", kind,
                payment.transaction_reference,
            )

            return FeeCharge.objects.get(payment=payment, kind=kind)

    # --- refunds (E9-S4) --------------------------------------------------

    def missed_guarantee(self, fee, actual_arrival):
        """Did Swayp miss what it promised when the fee was charged?"""
        if fee.guaranteed_arrival is None or actual_arrival is None:
            return False

        return actual_arrival > fee.guaranteed_arrival

    @transaction.atomic
    def refund(self, fee, *, reason="Delivery guarantee missed"):
        """Refund one fee. Idempotent — a fee refunds at most once."""
        locked = FeeCharge.objects.select_for_update().get(pk=fee.pk)

        if locked.state == FeeState.REFUNDED:
            return locked

        locked.state = FeeState.REFUNDED
        locked.refunded_at = timezone.now()
        locked.refund_reason = reason[:100]
        locked.save(
            update_fields=[
                "state", "refunded_at", "refund_reason", "updated_at",
            ]
        )

        self._notify_refund(locked)

        return locked

    def settle_guarantee(self, *, payment, actual_arrival):
        """Called when a payment lands: refund if the promise was missed.

        Only guaranteed kinds are considered, so a check overage is never
        refunded for arriving slowly — no promise was made about it.
        """
        refunded = []

        fees = FeeCharge.objects.filter(
            payment=payment,
            kind__in=GUARANTEED_KINDS,
        ).exclude(state=FeeState.REFUNDED)

        for fee in fees:
            if self.missed_guarantee(fee, actual_arrival):
                refunded.append(self.refund(fee))

        return refunded

    def _notify_refund(self, fee):
        from apps.notifications.models import Notification

        Notification.objects.create(
            user=fee.subscription.account,
            title="Fee refunded",
            message=(
                f"We missed the delivery guarantee on "
                f"{fee.payment.transaction_reference}, so the "
                f"${fee.amount} fee has been refunded."
            ),
            type="PAYMENT",
            metadata={
                "fee_charge_id": str(fee.id),
                "payment_id": str(fee.payment_id),
            },
        )
