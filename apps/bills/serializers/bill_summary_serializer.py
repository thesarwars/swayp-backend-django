from rest_framework import serializers


class BillSummarySerializer(serializers.Serializer):
    total_due_this_month = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
    )
    upcoming_count = serializers.IntegerField()
    due_count = serializers.IntegerField()
    overdue_count = serializers.IntegerField()
    # Bills, not occurrences — see docs/epics/epic-4-bills.md:7.
    total_bills = serializers.IntegerField()
    paid_count = serializers.IntegerField(
        help_text="Paid occurrences due this month."
    )
    scheduled_count = serializers.IntegerField(
        help_text="Occurrences queued to pay, any month (BILLS-8)."
    )