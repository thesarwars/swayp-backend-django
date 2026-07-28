from rest_framework import serializers

from apps.bills.models.bill_occurrence import BillOccurrence


class NextDueSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(
        source="bill.vendor.name",
        read_only=True,
    )

    vendor_logo = serializers.URLField(
        source="bill.vendor.logo",
        read_only=True,
    )

    category = serializers.CharField(
        source="bill.category.name",
        read_only=True,
    )

    class Meta:
        model = BillOccurrence
        fields = (
            "id",
            "vendor_name",
            "vendor_logo",
            "amount",
            "due_date",
            "category",
        )