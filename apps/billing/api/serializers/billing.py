from rest_framework import serializers

from apps.billing.models import (
    AddOnKind,
    EnterpriseAddOn,
    FeeCharge,
    Plan,
    PlanCode,
    Subscription,
)


class PlanSerializer(serializers.ModelSerializer):
    unlimited_seats = serializers.BooleanField(
        source="has_unlimited_seats", read_only=True
    )
    unlimited_banks = serializers.BooleanField(
        source="has_unlimited_banks", read_only=True
    )

    class Meta:
        model = Plan
        fields = (
            "code",
            "name",
            "monthly_price",
            "seat_limit",
            "bank_limit",
            "unlimited_seats",
            "unlimited_banks",
            "free_checks_per_month",
            "included_entities",
            "price_locked",
        )


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    effective_price = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    class Meta:
        model = Subscription
        fields = (
            "id",
            "plan",
            "status",
            "period_start",
            "period_end",
            "locked_price",
            "effective_price",
            "created_at",
        )


class SubscribeSerializer(serializers.Serializer):
    plan = serializers.ChoiceField(choices=PlanCode.choices)


class AddOnSerializer(serializers.ModelSerializer):
    line_total = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    class Meta:
        model = EnterpriseAddOn
        fields = ("id", "kind", "quantity", "unit_price", "line_total")


class SetAddOnSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=AddOnKind.choices)
    # 0 removes the add-on.
    quantity = serializers.IntegerField(min_value=0, default=1)


class FeeChargeSerializer(serializers.ModelSerializer):
    payment_reference = serializers.CharField(
        source="payment.transaction_reference", read_only=True
    )

    class Meta:
        model = FeeCharge
        fields = (
            "id",
            "kind",
            "amount",
            "state",
            "payment_reference",
            "guaranteed_arrival",
            "refunded_at",
            "refund_reason",
            "created_at",
        )


class InvoiceLineSerializer(serializers.Serializer):
    kind = serializers.CharField()
    description = serializers.CharField()
    quantity = serializers.IntegerField()
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=2)
    total = serializers.DecimalField(max_digits=18, decimal_places=2)


class InvoicePreviewSerializer(serializers.Serializer):
    subscription_id = serializers.UUIDField()
    plan = serializers.CharField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    lines = InvoiceLineSerializer(many=True)
    subtotal = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField()
