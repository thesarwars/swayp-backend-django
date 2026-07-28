from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.bills.models.bill_occurrence import BillOccurrence
from apps.bills.selectors.bill_occurrence_selector import BillOccurrenceSelector
from apps.common.enums import BillFrequency, BillOccurrenceStatus


class BillOccurrenceService:

    DEFAULT_OCCURRENCES = 12

    def __init__(self):
        self.selector = BillOccurrenceSelector()

    @transaction.atomic
    def generate_occurrences(self, bill):
        """
        Generate upcoming occurrences for a bill.
        """
        occurrences = []

        due_date = bill.anchor_date

        for _ in range(self.DEFAULT_OCCURRENCES):

            occurrences.append(
                BillOccurrence(
                    bill=bill,
                    due_date=due_date,
                    amount=bill.amount,
                    status=BillOccurrenceStatus.UPCOMING,
                )
            )

            due_date = self._get_next_due_date(
                due_date,
                bill.frequency,
            )

        BillOccurrence.objects.bulk_create(
            occurrences,
            ignore_conflicts=True,
        )

        return occurrences


    def _get_next_due_date(self,current_date,frequency):
            if frequency == BillFrequency.DAILY:
                return current_date + relativedelta(days=1)

            if frequency == BillFrequency.WEEKLY:
                return current_date + relativedelta(weeks=1)

            if frequency == BillFrequency.MONTHLY:
                return current_date + relativedelta(months=1)

            if frequency == BillFrequency.QUARTERLY:
                return current_date + relativedelta(months=3)

            if frequency == BillFrequency.YEARLY:
                return current_date + relativedelta(years=1)

            raise ValueError(
                f"Unsupported frequency: {frequency}"
            )

    
    def get_upcoming_occurrences(self, user):
        return self.selector.get_upcoming_occurrences(user)

    
    def mark_as_paid(self,occurrence,payment_reference):
        if occurrence.status == BillOccurrenceStatus.PAID:
            raise ValidationError(
                {
                    "detail": "Bill is already paid."
                }
            )

        occurrence.status = BillOccurrenceStatus.PAID
        occurrence.paid_at = timezone.now()
        occurrence.payment_reference = payment_reference

        occurrence.save(
            update_fields=[
                "status",
                "paid_at",
                "payment_reference",
            ]
        )

        return occurrence
    
    def get_summary(self, user):
        return self.selector.get_summary(user)

    def get_next_due(self, user):
        return self.selector.get_next_due(user)