from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bills.models.bill_occurrence import BillOccurrence
from apps.common.enums import BillOccurrenceStatus



class BillOccurrenceSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(
        source="bill.vendor.name",
        read_only=True,
    )
    category_name = serializers.CharField(
        source="bill.category.name",
        read_only=True,
    )

    # Effective status, not the stored column: UPCOMING/DUE/OVERDUE are
    # derived from due_date by the selector annotation.
    status = serializers.SerializerMethodField()

    @extend_schema_field(
        serializers.ChoiceField(choices=BillOccurrenceStatus.choices)
    )
    def get_status(self, obj):
        return getattr(obj, "computed_status", obj.status)

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