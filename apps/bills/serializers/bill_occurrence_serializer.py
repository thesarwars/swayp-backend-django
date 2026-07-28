from rest_framework import serializers
from apps.bills.models.bill_occurrence import BillOccurrence



class BillOccurrenceSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(
        source="bill.vendor.name",
        read_only=True,
    )
    category_name = serializers.CharField(
        source="bill.category.name",
        read_only=True,
    )

    class Meta:
        model = BillOccurrence
        fields = (
            "id",
            "due_date",
            "amount",
            "status",
            "vendor_name",
            "category_name",
        )