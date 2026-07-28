"""Failure detail and recovery (E6-S6).

A failed payment is terminal — it is never revived. Every recovery action
creates a **new** Payment against the same occurrence, linked back via
``retry_of``, so the history shows what was attempted and when.
"""

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.dates import estimated_arrival, initiation_date
from apps.common.enums import (
    BillOccurrenceStatus,
    PaymentStatus,
)
from apps.payments.models import Payment
from apps.payments.models.reference import create_with_reference
from apps.payments.services.authorization_text import processor_for_rail
from apps.payments.services.payment_create_service import PaymentCreateService

RETRY = "retry"
CHANGE_METHOD = "change_method"
RESCHEDULE = "reschedule"

ACTIONS = (RETRY, CHANGE_METHOD, RESCHEDULE)


class PaymentResolutionService:

    def __init__(self):
        self.create_service = PaymentCreateService()

    # --- failure detail ---------------------------------------------------

    def failure(self, *, user, payment_id, today=None):
        """Everything the failure screen shows (840:13131)."""
        today = today or timezone.localdate()

        payment = Payment.objects.filter(
            id=payment_id, user=user
        ).select_related(
            "vendor", "bill_occurrence", "bill_occurrence__bill"
        ).first()

        if payment is None:
            raise ValidationError({"payment": "Payment not found."})

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

        return {
            "payment_id": payment.id,
            "transaction_reference": payment.transaction_reference,
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
        """Late-fee rule and the countdown, from the vendor's own terms."""
        if vendor is None or vendor.late_fee_amount is None:
            return None

        grace_days = vendor.late_fee_grace_days or 0
        days_remaining = max(grace_days - days_overdue, 0)

        return {
            "amount": vendor.late_fee_amount,
            "grace_days": grace_days,
            "days_remaining": days_remaining,
            "applies": days_overdue > grace_days,
        }

    # --- resolution -------------------------------------------------------

    @transaction.atomic
    def resolve(self, *, user, payment_id, action, payment_method_id=None,
                scheduled_for=None, funding_account_id=None, today=None):
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
            raise ValidationError({"payment": "Payment not found."})

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
        )

        occurrence.status = BillOccurrenceStatus.SCHEDULED
        occurrence.save(update_fields=["status", "updated_at"])

        return {"action": action, "payment": replacement, "replaced": failed}

    def _assert_no_live_payment(self, occurrence):
        """An occurrence may only ever have one payment in flight."""
        live = Payment.objects.filter(
            bill_occurrence=occurrence,
            status__in=[
                PaymentStatus.SCHEDULED,
                PaymentStatus.PENDING,
                PaymentStatus.PROCESSING,
            ],
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
                     scheduled_for, today):
        funding_account = failed.funding_account

        if funding_account_id:
            funding_account = self.create_service._load_funding_account(
                failed.user, funding_account_id
            )

        rail = failed.rail
        anchor = scheduled_for or occurrence.due_date
        initiated = max(initiation_date(anchor, rail), today)

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
                    occurrence.bill.payment_method.method_type
                    if occurrence.bill.payment_method
                    else rail
                ),
                initiated_date=initiated,
                estimated_arrival=estimated_arrival(initiated, rail),
                cancellation_deadline=(
                    self.create_service.cancellation_deadline(initiated)
                ),
                scheduled_for=scheduled_for,
                retry_of=failed,
            )

        return create_with_reference(build, today=today)
