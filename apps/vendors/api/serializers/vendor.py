from decimal import Decimal

from rest_framework import serializers

from apps.bill_categories.models import BillCategory
from apps.common.enums import VendorSource
from apps.vendors.models.vendor import Vendor


#: Distinguishes "the queryset did not annotate this" from "it annotated
#: None", which is a real value meaning the vendor has no upcoming bill.
_MISSING = object()

class VendorListSerializer(serializers.ModelSerializer):

    payment_rail = serializers.SerializerMethodField()
    recurring_amount = serializers.SerializerMethodField()
    amount_period = serializers.SerializerMethodField()
    next_due = serializers.SerializerMethodField()

    class Meta:

        model = Vendor

        fields = (
            "id",
            "name",
            "logo",
            "business_type",
            "directory_verified",
            "payment_rail",
            "recurring_amount",
            "amount_period",
            "next_due",
        )

    # Each of these reads work the selector already batched. Doing it per row
    # instead cost three queries per vendor — a list of 30 vendors issued 90
    # extra queries, and the page got slower the more successful the customer
    # was.

    def get_payment_rail(self, obj):
        # ``primary_methods`` is the Prefetch(to_attr=...) from
        # VendorSelector.list. Calling obj.payment_methods.filter() here would
        # ignore that prefetch and re-query — which is exactly what it used to
        # do, with the prefetch sitting unused right beside it.
        primary = getattr(obj, "primary_methods", None)

        if primary is not None:
            return primary[0].method_type if primary else None

        # Detail and other callers do not annotate; fall back for them.
        method = obj.payment_methods.filter(is_primary=True).first()

        return method.method_type if method else None

    def _next_occurrence(self, obj):
        # Memoized per row so unannotated callers share one query.
        if not hasattr(obj, "_next_occ_cache"):
            from apps.vendors.selectors.vendor_selector import VendorSelector

            obj._next_occ_cache = VendorSelector.next_bill(obj)

        return obj._next_occ_cache

    def _annotated(self, obj, attr):
        """The annotation if the queryset carried one, else a sentinel.

        ``hasattr`` rather than a truth test: a vendor with no upcoming bill
        annotates to None, which is a real answer and must not send us back to
        the database for it.
        """
        return getattr(obj, attr, _MISSING)

    def get_recurring_amount(self, obj):
        value = self._annotated(obj, "next_amount")

        if value is _MISSING:
            occ = self._next_occurrence(obj)
            value = occ.amount if occ else None

        if value is None:
            return None

        # A Subquery returns the number without the column's scale, so $777.00
        # arrives as Decimal('777') and would serialise as "777". Money is a
        # 2dp string everywhere else in the API, and a client would not notice
        # the difference until it was reconciling to the cent.
        return Decimal(value).quantize(Decimal("0.01"))

    def get_amount_period(self, obj):
        value = self._annotated(obj, "next_frequency")

        if value is not _MISSING:
            return value

        occ = self._next_occurrence(obj)

        return occ.bill.frequency if occ else None

    def get_next_due(self, obj):
        value = self._annotated(obj, "next_due_date")

        if value is not _MISSING:
            return value

        occ = self._next_occurrence(obj)

        return occ.due_date if occ else None

from .vendor_payment_method import VendorPaymentMethodCreateSerializer, VendorPaymentMethodSerializer


class VendorDetailSerializer(serializers.ModelSerializer):

    payment_methods = VendorPaymentMethodSerializer(
        many=True,
        read_only=True,
    )

    # E3-S4 spend panel. Computed on demand so the list endpoint, which does
    # not need them, is not slowed down.
    total_paid = serializers.SerializerMethodField()
    monthly_spend = serializers.SerializerMethodField()
    next_bill = serializers.SerializerMethodField()
    bills = serializers.SerializerMethodField()

    class Meta:

        model = Vendor

        fields = (
            "id",
            "name",
            "category",
            "logo",
            "business_type",
            "notes",
            "source",
            "directory_verified",
            "late_fee_amount",
            "late_fee_grace_days",
            "payment_methods",
            "total_paid",
            "monthly_spend",
            "next_bill",
            "bills",
        )

    def get_total_paid(self, obj):
        from apps.vendors.selectors.vendor_selector import VendorSelector

        return VendorSelector.total_paid(obj)

    def get_monthly_spend(self, obj):
        from apps.vendors.selectors.vendor_selector import VendorSelector

        return VendorSelector.monthly_spend(obj)

    def get_next_bill(self, obj):
        from apps.vendors.selectors.vendor_selector import VendorSelector

        occurrence = VendorSelector.next_bill(obj)

        if occurrence is None:
            return None

        return {
            "occurrence_id": occurrence.id,
            "bill_id": occurrence.bill_id,
            "due_date": occurrence.due_date,
            "amount": occurrence.amount,
        }

    def get_bills(self, obj):
        """Capped list of the vendor's bills with read-time status chips."""
        from apps.vendors.selectors.vendor_selector import VendorSelector

        return [
            {
                "occurrence_id": occ.id,
                "bill_id": occ.bill_id,
                "category": (
                    occ.bill.category.name if occ.bill.category_id else None
                ),
                "amount": occ.amount,
                "due_date": occ.due_date,
                "status": occ.computed_status,
            }
            for occ in VendorSelector.recent_occurrences(obj)
        ]


class VendorUpdateSerializer(serializers.ModelSerializer):

    class Meta:

        model = Vendor

        fields = (
            "name",
            "category",
            "notes",
        )



class VendorCreateSerializer(serializers.Serializer):
    """
    Single endpoint for creating a Vendor.
    Supports three branches:
    - NETWORK
    - ACH
    - CHECK
    Business logic lives in VendorService.
    """

    name = serializers.CharField(max_length=150)
    category = serializers.PrimaryKeyRelatedField(
        queryset=BillCategory.objects.all()
    )
    source = serializers.ChoiceField(choices=VendorSource.choices)
    notes = serializers.CharField(required=False, allow_blank=True)

    payment_method = VendorPaymentMethodCreateSerializer()

    def validate(self, attrs):
        # Optional cross-field validation
        return attrs


class VendorSummarySerializer(serializers.Serializer):

    total = serializers.IntegerField()
    network = serializers.IntegerField()
    ach = serializers.IntegerField()
    check = serializers.IntegerField()
    check_total = serializers.DecimalField(max_digits=18,decimal_places=2,)