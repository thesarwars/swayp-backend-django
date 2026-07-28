"""Occurrence rows for the bills list screen (E4-S2).

The list shows occurrences — vendor + logo, due date, status chip, amount —
not bills. See the epic's design decision: "Total Bills 6" counts bills while
"Overdue 14 / Due 9 / Upcoming 14" counts occurrences.
"""

from rest_framework import serializers

from apps.bills.models.bill_occurrence import BillOccurrence


class BillOccurrenceRowSerializer(serializers.ModelSerializer):

    bill_id = serializers.UUIDField(source="bill.id", read_only=True)
    vendor_id = serializers.UUIDField(source="bill.vendor.id", read_only=True)
    vendor_name = serializers.CharField(
        source="bill.vendor.name", read_only=True
    )
    vendor_logo = serializers.CharField(
        source="bill.vendor.logo", read_only=True
    )
    category_name = serializers.CharField(
        source="bill.category.name", read_only=True
    )
    autopay_mode = serializers.CharField(
        source="bill.autopay_mode", read_only=True
    )
    status = serializers.SerializerMethodField()

    class Meta:
        model = BillOccurrence
        fields = (
            "id",
            "bill_id",
            "vendor_id",
            "vendor_name",
            "vendor_logo",
            "category_name",
            "due_date",
            "amount",
            "status",
            "autopay_mode",
        )

    def get_status(self, obj):
        return getattr(obj, "computed_status", obj.status)
