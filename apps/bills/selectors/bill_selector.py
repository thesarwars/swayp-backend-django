from django.db.models import Prefetch

from apps.bills.models.bill import Bill
from apps.bills.models.bill_occurrence import BillOccurrence


class BillSelector:

    def get_user_bills(self, user):
        return (
            Bill.objects.filter(user=user)
            .select_related(
                "vendor",
                "category",
                "payment_method",
            )
            .order_by("-created_at")
        )

    def get_bill(self, bill_id, user):
        return (
            Bill.objects.filter(
                id=bill_id,
                user=user,
            )
            .select_related(
                "vendor",
                "category",
                "payment_method",
            )
            .first()
        )

    def get_bill_detail(self, bill_id, user):
        return (
            Bill.objects.filter(
                id=bill_id,
                user=user,
            )
            .select_related(
                "vendor",
                "category",
                "payment_method",
            )
            .prefetch_related(
                Prefetch(
                    "occurrences",
                    queryset=BillOccurrence.objects.order_by("due_date"),
                )
            )
            .first()
        )
