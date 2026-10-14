from decimal import Decimal

from django.db.models import Max
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bills.models.bill import Bill
from apps.bills.selectors.occurrence_status import open_occurrences
from apps.common.dates import today_eastern
from apps.common.enums import BillOccurrenceStatus, VendorPaymentMethodType


def _money(value):
    return str(Decimal(value).quantize(Decimal("0.01")))


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

    # The ids an edit screen needs (BILLS-5); the names above are display.
    vendor_id = serializers.UUIDField(read_only=True)
    category_id = serializers.UUIDField(read_only=True)
    payment_method_id = serializers.UUIDField(read_only=True, allow_null=True)
    account_ref = serializers.SerializerMethodField()
    next_occurrence = serializers.SerializerMethodField()
    oldest_open_occurrence = serializers.SerializerMethodField()
    last_paid_at = serializers.SerializerMethodField()

    payment_method = serializers.SerializerMethodField()
    next_due = serializers.SerializerMethodField()
    overdue_amount = serializers.SerializerMethodField()
    days_overdue = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = (
            "id",
            "vendor_id",
            "vendor_name",
            "vendor_logo",
            "category_id",
            "bill_type",
            "amount",
            "category_name",
            "frequency",
            "anchor_date",
            "autopay_mode",
            "payment_method",
            "payment_method_id",
            "account_ref",
            "notes",
            "payment_ref",

            "next_due",
            "next_occurrence",
            "oldest_open_occurrence",
            "last_paid_at",
            "overdue_amount",
            "days_overdue",
            "total_paid",
        )

    @extend_schema_field(
        serializers.ChoiceField(
            choices=VendorPaymentMethodType.choices, allow_null=True
        )
    )
    def get_payment_method(self, obj):
        if obj.payment_method:
            return obj.payment_method.method_type
        return None
    
    # Eastern, not localdate(): the occurrence list, bills/summary/ and the
    # dashboard all classify against the user's calendar day, and a bill that
    # every other screen calls DUE must not be "1 day overdue" here.
    @extend_schema_field(serializers.DateField(allow_null=True))
    def get_next_due(self, obj):
        occurrence = (
            open_occurrences(obj.occurrences)
            .filter(due_date__gte=today_eastern())
            .order_by("due_date")
            .first()
        )

        if occurrence:
            return occurrence.due_date

        return None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_account_ref(self, obj):
        """The masked account, as on GET vendors/<id>/payment-methods: of
        the method the bill is actually paid by (its own, else the vendor's
        primary), as the payment engine resolves it."""
        from apps.payments.services.rails import method_for_bill

        method = method_for_bill(obj)

        if method is None or not method.account_last4:
            return None

        return f"****{method.account_last4}"

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "due_date": {"type": "string", "format": "date"},
                "amount": {"type": "string", "format": "decimal"},
                "status": {"type": "string", "enum": ["DUE", "UPCOMING"]},
            },
        }
    )
    def get_next_occurrence(self, obj):
        """The occurrence next_due describes, so the client can pay or
        schedule it without a second lookup (BILLS-5)."""
        today = today_eastern()

        occurrence = (
            open_occurrences(obj.occurrences)
            .filter(due_date__gte=today)
            .order_by("due_date")
            .first()
        )

        if occurrence is None:
            return None

        return {
            "id": occurrence.id,
            "due_date": occurrence.due_date,
            "amount": _money(occurrence.amount),
            "status": (
                BillOccurrenceStatus.DUE
                if occurrence.due_date == today
                else BillOccurrenceStatus.UPCOMING
            ),
        }

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "description": (
                "The earliest unpaid due date, past ones included, so the "
                "page can say \"11 days overdue\" (web C9). next_occurrence "
                "only looks forward. Null when nothing is open."
            ),
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "due_date": {"type": "string", "format": "date"},
                "amount": {"type": "string", "format": "decimal"},
                "status": {
                    "type": "string", "enum": ["OVERDUE", "DUE", "UPCOMING"],
                },
                "days_overdue": {"type": "integer"},
            },
        }
    )
    def get_oldest_open_occurrence(self, obj):
        today = today_eastern()

        occurrence = (
            open_occurrences(obj.occurrences).order_by("due_date").first()
        )

        if occurrence is None:
            return None

        if occurrence.due_date < today:
            status = BillOccurrenceStatus.OVERDUE
        elif occurrence.due_date == today:
            status = BillOccurrenceStatus.DUE
        else:
            status = BillOccurrenceStatus.UPCOMING

        return {
            "id": occurrence.id,
            "due_date": occurrence.due_date,
            "amount": _money(occurrence.amount),
            "status": status,
            "days_overdue": max((today - occurrence.due_date).days, 0),
        }

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_last_paid_at(self, obj):
        return obj.occurrences.filter(
            status=BillOccurrenceStatus.PAID
        ).aggregate(last=Max("paid_at"))["last"]

    # Money as a 2dp string, like the rest of the API (BILLS-5). These were
    # JSON numbers, and an integer 0 when nothing was owed.
    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=2))
    def get_overdue_amount(self, obj):
        overdue = open_occurrences(obj.occurrences).filter(
            due_date__lt=today_eastern(),
        )

        return _money(sum((item.amount for item in overdue), Decimal("0")))

    @extend_schema_field(serializers.IntegerField())
    def get_days_overdue(self, obj):
        today = today_eastern()

        oldest = (
            open_occurrences(obj.occurrences)
            .filter(due_date__lt=today)
            .order_by("due_date")
            .first()
        )

        if oldest is None:
            return 0

        return (today - oldest.due_date).days

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=2))
    def get_total_paid(self, obj):
        paid = obj.occurrences.filter(
            status=BillOccurrenceStatus.PAID,
        )

        return _money(sum((item.amount for item in paid), Decimal("0")))