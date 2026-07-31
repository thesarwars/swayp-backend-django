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
            "trial_days",
        )


class SubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    # Present only on the response that created the subscription, and only
    # when the processor wants the first charge confirmed (3-D Secure). Blank
    # everywhere else — it is a one-use secret, never stored.
    client_secret = serializers.SerializerMethodField()
    # status stays ACTIVE through a trial, so a client cannot tell from it
    # alone whether a charge has happened. These two say so directly.
    is_trialing = serializers.SerializerMethodField()
    trial_days_remaining = serializers.SerializerMethodField()
    effective_price = serializers.DecimalField(
        max_digits=18, decimal_places=2, read_only=True
    )

    def get_client_secret(self, subscription):
        return getattr(subscription, "pending_client_secret", "") or ""

    def get_is_trialing(self, subscription):
        return subscription.is_trialing()

    def get_trial_days_remaining(self, subscription):
        return subscription.trial_days_remaining()

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
            "provider_status",
            "client_secret",
            "trial_end",
            "is_trialing",
            "trial_days_remaining",
            "created_at",
        )


class SubscribeSerializer(serializers.Serializer):
    plan = serializers.ChoiceField(choices=PlanCode.choices)
    # Returned by the client after it collects a card against a SetupIntent.
    # The card itself never reaches Swayp — only this reference does.
    # Ignored while the mock provider is in use.
    payment_method_id = serializers.CharField(
        required=False, allow_blank=True, max_length=100
    )


class SetupIntentSerializer(serializers.Serializer):
    """What the client needs to mount a card form."""

    client_secret = serializers.CharField()
    publishable_key = serializers.CharField()
    collects_money = serializers.BooleanField()


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
