"""Create payments, singly or as a batch (E6-S2).

Selecting occurrences produces one Payment each plus a PaymentBatch when there
is more than one, marks the occurrences SCHEDULED so reminders stop, and
computes every date through the E1-S5 engine.

Nothing is executed here. Creation only reserves the work and returns the
authorization text; execution waits for confirmation (E6-S3).
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.banking.models import BankAccount, BankConnectionStatus
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.common.dates import (
    cutoff_datetime_et,
    estimated_arrival,
    initiation_date,
    today_eastern,
)
from apps.common.enums import (
    BillOccurrenceStatus,
    PaymentRail,
    PaymentStatus,
)
from apps.payments.models import Payment, PaymentBatch
from apps.payments.models.reference import create_with_reference
from apps.payments.selectors.live_payments import IN_FLIGHT_PAYMENT_STATUSES
from apps.payments.services.rails import rail_for_bill, rails_for_bill
from apps.payments.services.authorization_text import (
    for_batch,
    for_single,
    processor_for_rail,
)
from apps.common.exceptions import NotFoundException

#: Rails a client may request. CHECK is created the same way but mailed.
SELECTABLE_RAILS = {
    PaymentRail.ACH_STANDARD,
    PaymentRail.ACH_SAMEDAY,
    PaymentRail.NETWORK,
    PaymentRail.CHECK,
}


def deadline_sentence(deadline):
    """"I may cancel until 11:59 PM Eastern on August 1, 2026."

    Built by hand rather than with %-I/%-d, which are POSIX-only and raise on
    Windows.
    """
    if deadline is None:
        return None

    hour = deadline.hour % 12 or 12
    meridiem = "AM" if deadline.hour < 12 else "PM"

    return (
        f"I may cancel until {hour}:{deadline.minute:02d} {meridiem} Eastern "
        f"on {deadline.strftime('%B')} {deadline.day}, {deadline.year}."
    )


class PaymentCreateService:

    @transaction.atomic
    def create(self, *, user, occurrence_ids, funding_account_id=None,
               rail=None, scheduled_for=None, expedited=False, today=None):
        """``rail`` omitted means each bill's own: the rail its saved payment
        method implies, the same rule autopay uses (PAY-5). It used to be
        standard ACH for everything, so pay now on a check-only vendor went
        out over a rail that vendor cannot receive."""
        today = today or timezone.localdate()

        if rail is not None and rail not in SELECTABLE_RAILS:
            raise ValidationError({"rail": f"Unsupported rail: {rail}."})

        occurrences = self._load_occurrences(user, occurrence_ids)

        rails = {
            occurrence.id: rail or rail_for_bill(occurrence.bill)
            for occurrence in occurrences
        }

        if expedited and any(r != PaymentRail.CHECK for r in rails.values()):
            # Refused rather than ignored: silently dropping it would take the
            # customer's request for speed and give back the standard rail.
            raise ValidationError(
                {"expedited": "Only check payments can be expedited."}
            )

        self._assert_rails_fit(occurrences, rails, explicit=rail is not None)

        funding_account = self._load_funding_account(user, funding_account_id)

        batch = None
        if len(occurrences) > 1:
            batch = PaymentBatch.objects.create(
                user=user,
                total=sum(o.amount for o in occurrences),
                count=len(occurrences),
            )

        payments = [
            self._create_one(
                user=user,
                occurrence=occurrence,
                funding_account=funding_account,
                rail=rails[occurrence.id],
                scheduled_for=scheduled_for,
                expedited=expedited,
                batch=batch,
                today=today,
            )
            for occurrence in occurrences
        ]

        # Suppresses the reminder loop — an occurrence with a payment against
        # it must not keep nagging (E6-S9).
        BillOccurrence.objects.filter(
            id__in=[o.id for o in occurrences]
        ).update(status=BillOccurrenceStatus.SCHEDULED)

        return {
            "batch": batch,
            "payments": payments,
            "authorization_text": self._authorization_text(
                payments, funding_account, batch
            ),
        }

    def _create_one(self, *, user, occurrence, funding_account, rail,
                    scheduled_for, batch, today, expedited=False):
        bill = occurrence.bill
        processor = processor_for_rail(rail)

        # Work back from the due date so the money lands on time; a
        # future-dated send starts from its own date instead.
        anchor = scheduled_for or occurrence.due_date
        initiated = initiation_date(anchor, rail, expedited=expedited)

        if initiated < today:
            # The lead time has already passed, so the earliest honest start
            # is today rather than a date in the past.
            initiated = today

        arrival = estimated_arrival(initiated, rail, expedited=expedited)

        status = (
            PaymentStatus.SCHEDULED
            if scheduled_for
            else PaymentStatus.PENDING
        )

        def build(reference):
            return Payment.objects.create(
                user=user,
                bill_occurrence=occurrence,
                vendor=bill.vendor,
                category=bill.category,
                funding_account=funding_account,
                batch=batch,
                rail=rail,
                processor=processor,
                amount=occurrence.amount,
                fee=Decimal("0.00"),
                total=occurrence.amount,
                status=status,
                transaction_reference=reference,
                payment_method=(
                    bill.payment_method.method_type
                    if bill.payment_method
                    else rail
                ),
                initiated_date=initiated,
                estimated_arrival=arrival,
                cancellation_deadline=self.cancellation_deadline(initiated),
                scheduled_for=scheduled_for,
                expedited=expedited,
            )

        return create_with_reference(build, today=today)

    @transaction.atomic
    def reschedule(self, *, user, payment_id, scheduled_for, today=None):
        """Move an unconfirmed payment to another date, in place (PAY-7).

        It used to take cancel + create, which released and re-reserved the
        bill and issued a new reference. Only before confirm: once the user
        has authorized a date, a new date needs new consent, which is a new
        payment. ``scheduled_for`` None makes it pay-now again.
        """
        from apps.payments.services.confirm_service import (
            CONFIRMABLE,
            is_confirmed,
        )

        today = today or today_eastern()

        payment = (
            Payment.objects.select_for_update()
            .filter(id=payment_id, user=user)
            .select_related("bill_occurrence")
            .first()
        )

        if payment is None:
            raise NotFoundException("Payment not found.")

        if payment.status not in CONFIRMABLE or is_confirmed(payment):
            raise ValidationError(
                {
                    "payment": (
                        "Only an unconfirmed payment can be rescheduled. "
                        "Cancel it and create a new one instead."
                    )
                }
            )

        if scheduled_for is not None and scheduled_for < today:
            raise ValidationError(
                {"scheduled_for": "Choose today or a later date."}
            )

        anchor = scheduled_for or payment.bill_occurrence.due_date
        initiated = max(
            initiation_date(anchor, payment.rail, expedited=payment.expedited),
            today,
        )

        payment.scheduled_for = scheduled_for
        payment.initiated_date = initiated
        payment.estimated_arrival = estimated_arrival(
            initiated, payment.rail, expedited=payment.expedited
        )
        payment.cancellation_deadline = self.cancellation_deadline(initiated)
        payment.status = (
            PaymentStatus.SCHEDULED if scheduled_for else PaymentStatus.PENDING
        )
        payment.save(
            update_fields=[
                "scheduled_for",
                "initiated_date",
                "estimated_arrival",
                "cancellation_deadline",
                "status",
                "updated_at",
            ]
        )

        return payment

    @staticmethod
    def _assert_rails_fit(occurrences, rails, *, explicit):
        """An explicit rail has to suit each bill's saved method (PAY-5).

        Money goes to that method, so a check-only vendor cannot be paid by
        ACH. A bill with no saved method is left to fail as before, and
        only when the rail was chosen by the client: the omitted-rail path
        never picks a rail the method cannot take.
        """
        if not explicit:
            return

        for occurrence in occurrences:
            allowed = rails_for_bill(occurrence.bill)
            rail = rails[occurrence.id]

            if allowed and rail not in allowed:
                raise ValidationError(
                    {
                        "rail": (
                            f"{occurrence.bill.vendor.name} is paid by "
                            f"{occurrence.bill.payment_method.method_type}; "
                            f"{rail} is not available for it. Use one of: "
                            f"{', '.join(allowed)}."
                        )
                    }
                )

    def cancellation_deadline(self, initiated_date):
        """11:59 PM Eastern on the day before the debit starts.

        Aware and pinned to America/New_York, so the promise means the same
        wall-clock moment either side of a DST change.
        """
        return cutoff_datetime_et(initiated_date)

    def _load_occurrences(self, user, occurrence_ids):
        if not occurrence_ids:
            raise ValidationError(
                {"occurrence_ids": "Select at least one bill to pay."}
            )

        occurrences = list(
            BillOccurrence.objects.filter(
                id__in=occurrence_ids,
                bill__user=user,
                bill__deleted_at__isnull=True,
            ).select_related("bill", "bill__vendor", "bill__payment_method")
        )

        found = {str(o.id) for o in occurrences}
        missing = [str(i) for i in occurrence_ids if str(i) not in found]

        if missing:
            raise ValidationError(
                {"occurrence_ids": f"Unknown occurrence(s): {', '.join(missing)}."}
            )

        already_paid = [
            str(o.id)
            for o in occurrences
            if o.status == BillOccurrenceStatus.PAID
        ]

        if already_paid:
            raise ValidationError(
                {
                    "occurrence_ids": (
                        f"Already paid: {', '.join(already_paid)}."
                    )
                }
            )

        # One live payment per occurrence — paying the same bill twice because
        # a screen was left open is exactly what this prevents (E6-S9 AC).
        in_flight = Payment.objects.filter(
            bill_occurrence__in=occurrences,
            status__in=IN_FLIGHT_PAYMENT_STATUSES,
        ).values_list("bill_occurrence_id", flat=True)

        if in_flight:
            raise ValidationError(
                {
                    "occurrence_ids": (
                        "A payment is already in flight for "
                        f"{len(set(in_flight))} of these bills."
                    )
                }
            )

        return occurrences

    def _load_funding_account(self, user, funding_account_id):
        queryset = BankAccount.objects.filter(
            connection__user=user,
            connection__status=BankConnectionStatus.ACTIVE,
        )

        if funding_account_id:
            account = queryset.filter(id=funding_account_id).first()

            if account is None:
                raise ValidationError(
                    {"funding_account_id": "Funding account not found."}
                )

            return account

        account = queryset.filter(is_default_funding_source=True).first()

        if account is None:
            raise ValidationError(
                {
                    "funding_account_id": (
                        "No funding account is available. Connect a bank "
                        "account first."
                    )
                }
            )

        return account

    def _authorization_text(self, payments, funding_account, batch):
        display = (
            funding_account.masked_name if funding_account else "your account"
        )

        if batch is not None:
            return for_batch(
                total=sum(p.total for p in payments),
                count=len(payments),
                funding_display=display,
                processors=[p.processor for p in payments],
            )

        payment = payments[0]

        return for_single(
            amount=payment.total,
            vendor_name=payment.vendor.name if payment.vendor else "the vendor",
            funding_display=display,
            rail=payment.rail,
            processor=payment.processor,
            initiated_date=payment.initiated_date,
            deadline_text=deadline_sentence(payment.cancellation_deadline),
        )
