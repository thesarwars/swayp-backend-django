"""Payment history for a bill (E4-S4).

History joins Payment through the occurrence, so a retry — a second Payment
against the same occurrence — shows as its own row.
"""

from rest_framework import serializers

from apps.payments.models import Payment


class BillPaymentHistorySerializer(serializers.ModelSerializer):

    due_date = serializers.DateField(
        source="bill_occurrence.due_date", read_only=True
    )
    occurrence_id = serializers.UUIDField(
        source="bill_occurrence.id", read_only=True
    )
    payment_status = serializers.CharField(source="status", read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "occurrence_id",
            "due_date",
            "amount",
            "fee",
            "total",
            "currency",
            "payment_status",
            "payment_method",
            "transaction_reference",
            "created_at",
        )
