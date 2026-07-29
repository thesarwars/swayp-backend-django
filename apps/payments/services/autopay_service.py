"""Autopay scheduling and the REMIND loop (E6-S9).

An AUTO bill pays itself at its rail's lead time, backed by the standing
authorization captured when autopay was switched on (E4-S3) — there is no
per-payment confirm, because the user already consented to the series.

An AUTO bill whose authorization has been revoked does **nothing** and raises
an alert. Silently paying without live consent is the failure mode this guards
against.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.bills.models.bill_occurrence import BillOccurrence
from apps.common.dates import initiation_date
from apps.common.enums import (
    AutopayMode,
    BillOccurrenceStatus,
    NotificationType,
    PaymentRail,
    PaymentStatus,
)
from apps.notifications.services import notify
from apps.payments.models import Payment
from apps.payments.services.payment_create_service import PaymentCreateService

logger = logging.getLogger(__name__)

#: Rail per stored payment-method type.
RAIL_BY_METHOD = {
    "ACH": PaymentRail.ACH_STANDARD,
    "NETWORK": PaymentRail.NETWORK,
    "CHECK": PaymentRail.CHECK,
}


class AutopayService:

    def __init__(self):
        self.create_service = PaymentCreateService()

    def due_occurrences(self, today=None):
        """AUTO occurrences whose lead time has arrived.

        Selected by comparing today against the initiation date for each
        occurrence's rail, so a check goes out days before an ACH debit for
        the same due date.
        """
        today = today or timezone.localdate()

        candidates = (
            BillOccurrence.objects.filter(
                bill__autopay_mode=AutopayMode.AUTO,
                bill__deleted_at__isnull=True,
                status__in=[
                    BillOccurrenceStatus.UPCOMING,
                    BillOccurrenceStatus.DUE,
                    BillOccurrenceStatus.OVERDUE,
                ],
            )
            .select_related(
                "bill", "bill__vendor", "bill__payment_method", "bill__user"
            )
        )

        due = []

        for occurrence in candidates:
            rail = self.rail_for(occurrence.bill)

            if initiation_date(occurrence.due_date, rail) <= today:
                due.append(occurrence)

        return due

    def rail_for(self, bill):
        method = bill.payment_method

        if method is None:
            return PaymentRail.ACH_STANDARD

        return RAIL_BY_METHOD.get(
            method.method_type, PaymentRail.ACH_STANDARD
        )

    def has_live_authorization(self, bill):
        return bill.standing_authorizations.filter(
            revoked_at__isnull=True
        ).exists()

    def run(self, today=None):
        today = today or timezone.localdate()

        created = 0
        skipped = 0
        unauthorized = 0

        for occurrence in self.due_occurrences(today):
            bill = occurrence.bill

            if not self.has_live_authorization(bill):
                unauthorized += 1
                self._alert_missing_authorization(bill)
                continue

            if self._already_in_flight(occurrence):
                skipped += 1
                continue

            try:
                self._pay(occurrence, today)
                created += 1
            except Exception:
                logger.exception(
                    "autopay failed for occurrence %s", occurrence.pk
                )
                skipped += 1

        return {
            "created": created,
            "skipped": skipped,
            "unauthorized": unauthorized,
        }

    def _already_in_flight(self, occurrence):
        return Payment.objects.filter(
            bill_occurrence=occurrence,
            status__in=[
                PaymentStatus.SCHEDULED,
                PaymentStatus.PENDING,
                PaymentStatus.PROCESSING,
            ],
        ).exists()

    @transaction.atomic
    def _pay(self, occurrence, today):
        """Create and immediately execute — the standing auth is the consent."""
        bill = occurrence.bill

        result = self.create_service.create(
            user=bill.user,
            occurrence_ids=[occurrence.id],
            rail=self.rail_for(bill),
            today=today,
        )

        payment = result["payments"][0]

        payment.status = PaymentStatus.PROCESSING
        payment.save(update_fields=["status", "updated_at"])

        from apps.payments.services.stage_service import StageService
        from apps.common.enums import PaymentStageStatus
        from apps.payments.models import PaymentStageName

        stages = StageService()
        stages.seed(payment)
        stages.mark(
            payment, PaymentStageName.AUTHORIZED, PaymentStageStatus.DONE,
            detail="Standing authorization",
        )

        from apps.payments.tasks import execute_payment

        transaction.on_commit(
            lambda: execute_payment.delay(payment_id=str(payment.id))
        )

        notify(
            bill.user,
            NotificationType.AUTOPAY_EXECUTED,
            {
                "vendor_name": bill.vendor.name,
                "amount": str(occurrence.amount),
                "due_date": str(occurrence.due_date),
                "bill_id": str(bill.id),
                "occurrence_id": str(occurrence.id),
                "payment_id": str(payment.id),
            },
        )

        return payment

    def _alert_missing_authorization(self, bill):
        logger.error(
            "autopay: bill %s is AUTO with no live standing authorization",
            bill.pk,
        )

        # SYSTEM, not AUTOPAY_EXECUTED (its inverse) and not PAYMENT_FAILED
        # (no Payment row exists on this branch). The enum has no member for
        # "autopay could not run"; this changes the wire value from PAYMENT.
        notify(
            bill.user,
            NotificationType.SYSTEM,
            {"bill_id": str(bill.id), "vendor_name": bill.vendor.name},
            title="Autopay needs your attention",
            message=(
                f"Autopay for {bill.vendor.name} could not run because the "
                "authorization is no longer active. Re-enable autopay to "
                "continue."
            ),
        )


class ReminderService:
    """The REMIND half of E6-S9.

    Notifies rather than pays, and carries the ids the approval screen needs so
    the user's approval calls the normal create endpoint.
    """

    def due_reminders(self, today=None):
        today = today or timezone.localdate()

        return (
            BillOccurrence.objects.filter(
                bill__autopay_mode=AutopayMode.REMIND,
                bill__deleted_at__isnull=True,
                due_date__lte=today,
                status__in=[
                    BillOccurrenceStatus.UPCOMING,
                    BillOccurrenceStatus.DUE,
                    BillOccurrenceStatus.OVERDUE,
                ],
            )
            .select_related("bill", "bill__vendor", "bill__user")
        )

    def run(self, today=None):
        from apps.notifications.models import Notification

        sent = 0

        for occurrence in self.due_reminders(today):
            # A scheduled payment already stops the nagging; this is the
            # belt-and-braces check for occurrences paid another way.
            if Payment.objects.filter(
                bill_occurrence=occurrence,
                status__in=[
                    PaymentStatus.SCHEDULED,
                    PaymentStatus.PENDING,
                    PaymentStatus.PROCESSING,
                    PaymentStatus.SUCCESSFUL,
                ],
            ).exists():
                continue

            bill = occurrence.bill

            Notification.objects.create(
                user=bill.user,
                title=f"{bill.vendor.name} is due",
                message=(
                    f"{bill.vendor.name} for {occurrence.amount} was due on "
                    f"{occurrence.due_date}. Approve it to pay."
                ),
                type="PAYMENT",
                metadata={
                    "bill_id": str(bill.id),
                    "occurrence_id": str(occurrence.id),
                },
            )
            sent += 1

        return sent
