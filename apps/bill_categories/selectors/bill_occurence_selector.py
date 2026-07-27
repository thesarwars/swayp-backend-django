from django.db.models.aggregates import Sum
from django.utils import timezone
from apps.bill_categories.models.bill_occurrence import BillOccurrence
from apps.common.enums import BillOccurrenceStatus


class BillOccurrenceSelector:

    def get_upcoming_occurrences(self, user):
        return (
            BillOccurrence.objects.filter(
                bill__user=user,
                status=BillOccurrenceStatus.UPCOMING,
                due_date__gte=timezone.localdate(),
            )
            .select_related(
                "bill",
                "bill__vendor",
                "bill__category",
            )
            .order_by("due_date")
        )
    
    def get_summary(self, user):
        today = timezone.localdate()

        queryset = BillOccurrence.objects.filter(
            bill__user=user,
        )

        return {
            "total_due_this_month": queryset.filter(
                due_date__year=today.year,
                due_date__month=today.month,
            ).aggregate(
                total=Sum("amount")
            )["total"] or 0,

            "upcoming_count": queryset.filter(
                status=BillOccurrenceStatus.UPCOMING,
                due_date__gt=today,
            ).count(),

            "due_count": queryset.filter(
                status=BillOccurrenceStatus.UPCOMING,
                due_date=today,
            ).count(),

            "overdue_count": queryset.filter(
                status=BillOccurrenceStatus.UPCOMING,
                due_date__lt=today,
            ).count(),
        }
    
    def get_next_due(self, user):
        return (
            BillOccurrence.objects.filter(
                bill__user=user,
                status=BillOccurrenceStatus.UPCOMING,
                due_date__gte=timezone.localdate(),
            )
            .select_related(
                "bill",
                "bill__vendor",
                "bill__category",
            )
            .order_by("due_date")
            .first()
        )