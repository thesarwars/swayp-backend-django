"""Failure detail and recovery (E6-S6).

A failed payment is terminal — it is never revived. Every recovery action
creates a **new** Payment against the same occurrence, linked back via
``retry_of``, so the history shows what was attempted and when.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.dates import (
    estimated_arrival,
    initiation_date,
    today_eastern,
)
from apps.common.enums import (
    BillOccurrenceStatus,
    PaymentRail,
    PaymentStatus,
)
from apps.payments.models import Payment
from apps.payments.models.reference import create_with_reference
from apps.payments.selectors.live_payments import IN_FLIGHT_PAYMENT_STATUSES
from apps.payments.services.authorization_text import processor_for_rail
from apps.payments.services.payment_create_service import PaymentCreateService
from apps.payments.services.rails import method_for_bill, rail_for_bill
from apps.vendors.services.late_fee import grace_days, has_late_fee_policy
from apps.common.exceptions import NotFoundException

RETRY = "retry"
CHANGE_METHOD = "change_method"
RESCHEDULE = "reschedule"

ACTIONS = (RETRY, CHANGE_METHOD, RESCHEDULE)

#: Display-ready wording per failure reason (PAY-6), so every client shows
#: the same words instead of mapping codes itself. Unknown reasons fall back
#: to the generic pair.
FAILURE_COPY = {
    "NSF": (
        "Not enough money in the account",
        "Your bank declined the debit because the account didn't have "
        "enough funds at the time. Add funds or choose another account, "
        "then try again.",
    ),
    "ACH_RETURN": (
        "Your bank returned the payment",
        "The bank sent the debit back. Check the account, or choose another "
        "account or payment method, then try again.",
    ),
    "PROCESSOR_DECLINED": (
        "The payment was declined",
        "Our payment provider couldn't process this payment. Try again, or "
        "choose another payment method.",
    ),
}

GENERIC_FAILURE_COPY = (
    "The payment didn't go through",
    "Something stopped this payment. Try again, or choose another payment "
    "method.",
)


class PaymentResolutionService:

    def __init__(self):
        self.create_service = PaymentCreateService()

    # --- failure detail ---------------------------------------------------

    def failure(self, *, user, payment_id, today=None):
        """Everything the failure screen shows (840:13131)."""
        # Eastern, not localdate(). days_overdue and the late-fee block below
        # are the same claim about the same occurrence that the E8-S4 warning
        # job makes, and localdate() rolls over at 19:00/20:00 ET: on the last
        # evening of a grace period this screen would announce the fee had
        # landed while the notifier was still counting down to it. Sharing the
        # arithmetic (apps/vendors/services/late_fee.py) is only worth
        # anything if both surfaces also agree which day it is.
        today = today or today_eastern()

        payment = Payment.objects.filter(
            id=payment_id, user=user
        ).select_related(
            "vendor", "bill_occurrence", "bill_occurrence__bill"
        ).first()

        if payment is None:
            raise NotFoundException("Payment not found.")

        if payment.status != PaymentStatus.FAILED:
            raise ValidationError(
                {
                    "payment": (
                        f"Payment {payment.transaction_reference} did not "
                        "fail."
                    )
                }
            )

        occurrence = payment.bill_occurrence
        vendor = payment.vendor

        days_overdue = 0
        if occurrence and occurrence.due_date < today:
            days_overdue = (today - occurrence.due_date).days

        title, explanation = FAILURE_COPY.get(
            payment.failure_reason, GENERIC_FAILURE_COPY
        )

        return {
            "payment_id": payment.id,
            "transaction_reference": payment.transaction_reference,
            "title": title,
            "explanation": explanation,
            "amount": payment.total,
            "vendor_name": vendor.name if vendor else None,
            "failed_at": payment.updated_at,
            "failure_reason": payment.failure_reason,
            "failure_detail": payment.failure_detail,
            "due_date": occurrence.due_date if occurrence else None,
            "days_overdue": days_overdue,
            "late_fee": self._late_fee(vendor, days_overdue),
            "available_actions": list(ACTIONS),
        }

    def _late_fee(self, vendor, days_overdue):
        """Late-fee rule and the countdown, from the vendor's own terms.

        Policy detection is shared with the E8-S4 warning job so the two
        surfaces cannot disagree about whether a vendor has a policy — a
        $0.00 fee is not one, and "$0.00 in 3 days" is not a warning.
        """
        if not has_late_fee_policy(vendor):
            return None

        grace = grace_days(vendor)

        return {
            "amount": vendor.late_fee_amount,
            "grace_days": grace,
            "days_remaining": max(grace - days_overdue, 0),
            "applies": days_overdue > grace,
        }

    # --- resolution -------------------------------------------------------

    @transaction.atomic
    def resolve(self, *, user, payment_id, action, payment_method_id=None,
                scheduled_for=None, funding_account_id=None, today=None):
        # Deliberately still localdate(), unlike failure() above: this `today`
        # dates a *payment* — it floors initiated_date and stamps the
        # reference sequence — and PaymentCreateService.create
        # (payment_create_service.py:66) and create_with_reference
        # (models/reference.py:20) date theirs the same way. Moving one of the
        # three to Eastern on its own is how the money path starts
        # disagreeing with itself; they move together, in their own commit.
        today = today or timezone.localdate()

        if action not in ACTIONS:
            raise ValidationError(
                {"action": f"Unknown action. Choose one of {ACTIONS}."}
            )

        failed = (
            Payment.objects.select_for_update()
            .filter(id=payment_id, user=user)
            .first()
        )

        if failed is None:
            raise NotFoundException("Payment not found.")

        if failed.status != PaymentStatus.FAILED:
            raise ValidationError(
                {"payment": "Only a failed payment can be resolved."}
            )

        occurrence = failed.bill_occurrence

        if occurrence is None:
            raise ValidationError(
                {
                    "payment": (
                        "This payment is not linked to a bill, so it cannot "
                        "be retried automatically."
                    )
                }
            )

        self._assert_no_live_payment(occurrence)

        if action == CHANGE_METHOD:
            self._switch_method(occurrence, payment_method_id)

        send_date = scheduled_for if action == RESCHEDULE else None

        if action == RESCHEDULE and not send_date:
            raise ValidationError(
                {"scheduled_for": "A new date is required to reschedule."}
            )

        replacement = self._new_attempt(
            failed=failed,
            occurrence=occurrence,
            funding_account_id=funding_account_id,
            scheduled_for=send_date,
            today=today,
            method_changed=action == CHANGE_METHOD,
        )

        occurrence.status = BillOccurrenceStatus.SCHEDULED
        occurrence.save(update_fields=["status", "updated_at"])

        # The replacement is a new payment with no consent behind it yet, so
        # the user confirms it like any other (PAY-6). The text is what they
        # agree to; it lapses like any unconfirmed payment (PAY-1).
        return {
            "action": action,
            "payment": replacement,
            "replaced": failed,
            "authorization_text": self.create_service._authorization_text(
                [replacement], replacement.funding_account, None
            ),
        }

    def _assert_no_live_payment(self, occurrence):
        """An occurrence may only ever have one payment in flight."""
        live = Payment.objects.filter(
            bill_occurrence=occurrence,
            status__in=IN_FLIGHT_PAYMENT_STATUSES,
        ).exists()

        if live:
            raise ValidationError(
                {
                    "payment": (
                        "A payment for this bill is already in flight."
                    )
                }
            )

    def _switch_method(self, occurrence, payment_method_id):
        from apps.vendors.models import VendorPaymentMethod

        if not payment_method_id:
            raise ValidationError(
                {
                    "payment_method_id": (
                        "A payment method is required to change it."
                    )
                }
            )

        method = VendorPaymentMethod.objects.filter(
            id=payment_method_id, vendor=occurrence.bill.vendor
        ).first()

        if method is None:
            raise ValidationError(
                {"payment_method_id": "Payment method not found."}
            )

        occurrence.bill.payment_method = method
        occurrence.bill.save(update_fields=["payment_method", "updated_at"])

        return method

    def _new_attempt(self, *, failed, occurrence, funding_account_id,
                     scheduled_for, today, method_changed=False):
        funding_account = failed.funding_account

        if funding_account_id:
            funding_account = self.create_service._load_funding_account(
                failed.user, funding_account_id
            )

        rail = failed.rail

        # A new method takes its own rail. Keeping the failed payment's would
        # send, say, a check-method payment over ACH, to a vendor who now
        # has no ACH account on file (PAY-6).
        if method_changed:
            rail = rail_for_bill(occurrence.bill)

        # A retry of an expedited check stays expedited: the customer paid
        # for speed and the failure was not theirs. It is charged again
        # because it is a second physical check, and it is refunded again
        # under the same guarantee if it is late.
        expedited = failed.expedited and rail == PaymentRail.CHECK
        anchor = scheduled_for or occurrence.due_date
        initiated = max(
            initiation_date(anchor, rail, expedited=expedited), today
        )

        status = (
            PaymentStatus.SCHEDULED if scheduled_for else PaymentStatus.PENDING
        )

        def build(reference):
            return Payment.objects.create(
                user=failed.user,
                bill_occurrence=occurrence,
                vendor=failed.vendor,
                category=failed.category,
                funding_account=funding_account,
                rail=rail,
                processor=processor_for_rail(rail),
                amount=occurrence.amount,
                total=occurrence.amount,
                status=status,
                transaction_reference=reference,
                payment_method=(
                    method.method_type
                    if (method := method_for_bill(occurrence.bill))
                    else rail
                ),
                initiated_date=initiated,
                estimated_arrival=estimated_arrival(
                    initiated, rail, expedited=expedited
                ),
                cancellation_deadline=(
                    self.create_service.cancellation_deadline(initiated)
                ),
                scheduled_for=scheduled_for,
                expedited=expedited,
                retry_of=failed,
            )

        return create_with_reference(build, today=today)
