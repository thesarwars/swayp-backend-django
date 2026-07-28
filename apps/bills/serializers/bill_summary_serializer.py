from rest_framework import serializers


class BillSummarySerializer(serializers.Serializer):
    total_due_this_month = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
    )
    upcoming_count = serializers.IntegerField()
    due_count = serializers.IntegerField()
    overdue_count = serializers.IntegerField()