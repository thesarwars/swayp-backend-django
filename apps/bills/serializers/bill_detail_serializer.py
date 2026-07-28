from django.utils import timezone
from rest_framework import serializers

from apps.bills.models.bill import Bill
from apps.bills.selectors.occurrence_status import open_occurrences
from apps.common.enums import BillOccurrenceStatus


class BillDetailSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(
        source="vendor.name",
        read_only=True,
    )

    vendor_logo = serializers.URLField(
        source="vendor.logo",
        read_only=True,
    )

    category_name = serializers.CharField(source="category.name",read_only=True)
    payment_method = serializers.SerializerMethodField()
    next_due = serializers.SerializerMethodField()
    overdue_amount = serializers.SerializerMethodField()
    days_overdue = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = (
            "id",
            "vendor_name",
            "vendor_logo",
            "bill_type",
            "amount",
            "category_name",
            "frequency",
            "anchor_date",
            "autopay_mode",
            "payment_method",
            "notes",

            "next_due",
            "overdue_amount",
            "days_overdue",
            "total_paid",
        )

    def get_payment_method(self, obj):
        if obj.payment_method:
            return obj.payment_method.method_type
        return None
    
    def get_next_due(self, obj):
        occurrence = (
            open_occurrences(obj.occurrences)
            .filter(due_date__gte=timezone.localdate())
            .order_by("due_date")
            .first()
        )

        if occurrence:
            return occurrence.due_date

        return None

    def get_overdue_amount(self, obj):
        overdue = open_occurrences(obj.occurrences).filter(
            due_date__lt=timezone.localdate(),
        )

        return sum(item.amount for item in overdue)

    def get_days_overdue(self, obj):
        today = timezone.localdate()

        oldest = (
            open_occurrences(obj.occurrences)
            .filter(due_date__lt=today)
            .order_by("due_date")
            .first()
        )

        if oldest is None:
            return 0

        return (today - oldest.due_date).days

    def get_total_paid(self, obj):
        paid = obj.occurrences.filter(
            status=BillOccurrenceStatus.PAID,
        )

        return sum(item.amount for item in paid)