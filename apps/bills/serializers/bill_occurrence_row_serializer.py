"""Occurrence rows for the bills list screen (E4-S2).

The list shows occurrences — vendor + logo, due date, status chip, amount —
not bills. See the epic's design decision: "Total Bills 6" counts bills while
"Overdue 14 / Due 9 / Upcoming 14" counts occurrences.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bills.models.bill_occurrence import BillOccurrence
from apps.common.dates import today_eastern
from apps.common.enums import BillOccurrenceStatus, VendorPaymentMethodType


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
    # The id behind category_name (BILLS-14), so a row is tied to its
    # category without comparing names.
    category_id = serializers.UUIDField(
        source="bill.category_id", read_only=True
    )
    payment_method = serializers.SerializerMethodField()
    days_overdue = serializers.SerializerMethodField()
    payment_id = serializers.SerializerMethodField()
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
            "category_id",
            "category_name",
            "due_date",
            "amount",
            "status",
            "days_overdue",
            "autopay_mode",
            "payment_method",
            "payment_id",
        )

    @extend_schema_field(serializers.ChoiceField(choices=BillOccurrenceStatus.choices))
    def get_status(self, obj):
        return getattr(obj, "computed_status", obj.status)

    @extend_schema_field(
        serializers.ChoiceField(
            choices=VendorPaymentMethodType.choices, allow_null=True
        )
    )
    def get_payment_method(self, obj):
        """The bill's saved method type, or null (BILLS-8)."""
        method = obj.bill.payment_method

        return method.method_type if method else None

    @extend_schema_field(serializers.IntegerField())
    def get_days_overdue(self, obj):
        """Calendar days past due for an OVERDUE row, else 0 (BILLS-8).

        The same count bill detail reports, so the two screens agree.
        """
        if self.get_status(obj) != BillOccurrenceStatus.OVERDUE:
            return 0

        return (today_eastern() - obj.due_date).days

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_payment_id(self, obj):
        """The payment standing behind a SCHEDULED or PAID row (BILLS-8).

        Null on other rows, and on a row marked paid outside Swayp, which
        has no payment. Read from the annotation; a queryset without it
        answers null rather than querying per row.
        """
        if self.get_status(obj) not in (
            BillOccurrenceStatus.SCHEDULED,
            BillOccurrenceStatus.PAID,
        ):
            return None

        return getattr(obj, "active_payment_id", None)
