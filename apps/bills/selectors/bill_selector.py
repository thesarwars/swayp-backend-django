from django.db.models import Prefetch

from apps.bills.models.bill import Bill
from apps.bills.models.bill_occurrence import BillOccurrence


class BillSelector:

    def get_user_bills(self, user):
        return (
            Bill.objects.filter(user=user, deleted_at__isnull=True)
            .select_related(
                "vendor",
                "category",
                "payment_method",
            )
            .order_by("-created_at")
        )

    def count_active_bills(self, user):
        """How many live bills the user has — the "Total Bills 6" stat.

        Bills, not occurrences (docs/epics/epic-4-bills.md:7). The filter is
        the one ``get_user_bills`` uses, so this equals the row count of the
        unpaginated GET /api/v1/bills/.
        """
        return Bill.objects.filter(
            user=user, deleted_at__isnull=True
        ).count()

    def get_bill(self, bill_id, user):
        return (
            Bill.objects.filter(
                id=bill_id,
                user=user,
                deleted_at__isnull=True,
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
                deleted_at__isnull=True,
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
