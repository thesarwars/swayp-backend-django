from rest_framework import serializers

from apps.billing.models import (
    AddOnKind,
    EnterpriseAddOn,
    FeeCharge,
    FeeState,
    Plan,
    PlanCode,
    Subscription,
    SubscriptionStatus,
)
from apps.billing.models.plan import (
    BILLING_INTERVAL,
    PLAN_DESCRIPTIONS,
    plan_features,
)
from apps.common.serializers import PaginationQuerySerializer


class PlanSerializer(serializers.ModelSerializer):
    unlimited_seats = serializers.BooleanField(
        source="has_unlimited_seats", read_only=True
    )
    unlimited_banks = serializers.BooleanField(
        source="has_unlimited_banks", read_only=True
    )
    description = serializers.SerializerMethodField()
    features = serializers.SerializerMethodField(
        help_text="Feature lines for the pricing screen, in display order."
    )
    billing_interval = serializers.SerializerMethodField(
        help_text='Always "month"; there is no annual price.'
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
            "description",
            "features",
            "billing_interval",
        )

    def get_description(self, plan) -> str:
        return PLAN_DESCRIPTIONS.get(plan.code, "")

    def get_features(self, plan) -> list[str]:
        return plan_features(plan)

    def get_billing_interval(self, plan) -> str:
        return BILLING_INTERVAL


class PlanOfferSerializer(PlanSerializer):
    """A plan as offered to this account (BILLING-4).

    trial_days and price_locked describe the plan; these say whether this
    account would actually get them, so the badge and the button can stop
    promising a trial to a returning customer or a lock to customer 501.
    """

    trial_eligible = serializers.SerializerMethodField(
        help_text="Subscribing now starts the plan's free trial."
    )
    lock_available = serializers.SerializerMethodField(
        help_text="Subscribing now locks this plan's price (Founding only)."
    )
    founding_spots_remaining = serializers.SerializerMethodField(
        help_text="Price-locked Founding spots left; null on other plans."
    )

    class Meta(PlanSerializer.Meta):
        fields = PlanSerializer.Meta.fields + (
            "trial_eligible",
            "lock_available",
            "founding_spots_remaining",
        )

    def get_trial_eligible(self, plan) -> bool:
        return bool(plan.trial_days) and self.context["trial_eligible"]

    def get_lock_available(self, plan) -> bool:
        return plan.price_locked and self.context["spots_remaining"] > 0

    def get_founding_spots_remaining(self, plan) -> int | None:
        return self.context["spots_remaining"] if plan.price_locked else None


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
    past_due = serializers.SerializerMethodField(
        help_text=(
            "The last charge failed. The plan stays in force; replace the "
            "card (POST billing/payment-method) to recover."
        )
    )

    cancel_pending = serializers.SerializerMethodField(
        help_text="Cancelled, still live until cancels_on."
    )

    def get_cancel_pending(self, subscription) -> bool:
        return subscription.cancels_on is not None

    def get_past_due(self, subscription) -> bool:
        return subscription.status == SubscriptionStatus.PAST_DUE

    def get_client_secret(self, subscription) -> str | None:
        return getattr(subscription, "pending_client_secret", "") or ""

    def get_is_trialing(self, subscription) -> bool:
        return subscription.is_trialing()

    def get_trial_days_remaining(self, subscription) -> int | None:
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
            "past_due",
            "cancel_pending",
            "cancels_on",
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


class FeeChargeQuerySerializer(PaginationQuerySerializer):
    """Filters for the fee ledger (BILLING-9). Applied before paging."""

    state = serializers.ChoiceField(choices=FeeState.choices, required=False)
    from_date = serializers.DateField(
        required=False, help_text="Charged on or after this day."
    )
    to_date = serializers.DateField(
        required=False, help_text="Charged on or before this day."
    )

    def validate(self, attrs):
        start, end = attrs.get("from_date"), attrs.get("to_date")

        if start and end and start > end:
            raise serializers.ValidationError(
                {"to_date": "Must be on or after from_date."}
            )

        return attrs


class FeeChargeSerializer(serializers.ModelSerializer):
    payment_id = serializers.UUIDField(source="payment.id", read_only=True)
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
            "payment_id",
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
    state = serializers.ChoiceField(
        choices=FeeState.choices, allow_null=True,
        help_text="Fee lines only: PENDING or REFUNDED. Null otherwise.",
    )
    fee_charge_id = serializers.UUIDField(allow_null=True)
    payment_reference = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField(allow_null=True)


class InvoicePreviewSerializer(serializers.Serializer):
    subscription_id = serializers.UUIDField()
    plan = serializers.CharField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    lines = InvoiceLineSerializer(many=True)
    subtotal = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField()
    next_charge_date = serializers.DateField(
        allow_null=True,
        help_text=(
            "When the card is next billed: trial_end during a trial, else "
            "period_end. Null if the plan is cancelling or nothing is "
            "collected."
        ),
    )


class CardSerializer(serializers.Serializer):
    """The card on file, as safe to show (BILLING-1)."""

    brand = serializers.CharField(help_text="e.g. visa, mastercard")
    last4 = serializers.CharField()
    exp_month = serializers.IntegerField()
    exp_year = serializers.IntegerField()


class ReplaceCardSerializer(serializers.Serializer):
    payment_method_id = serializers.CharField(
        help_text="From a SetupIntent confirmed with the processor's SDK."
    )


class BillingConfigSerializer(serializers.Serializer):
    collects_money = serializers.BooleanField(
        help_text="False on the mock deployment: no card is ever collected."
    )
    publishable_key = serializers.CharField(
        allow_blank=True, help_text="For the processor's client SDK; \"\" when none."
    )


class InvoiceHistoryQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        min_value=1, max_value=100, default=20, required=False
    )
    starting_after = serializers.CharField(
        required=False, allow_blank=True, default="",
        help_text="The last invoice id of the previous page (next_cursor).",
    )


class InvoiceHistoryItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    number = serializers.CharField(allow_blank=True)
    status = serializers.CharField(
        help_text="paid, open, void, uncollectible or draft."
    )
    total = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField()
    created = serializers.DateTimeField(allow_null=True)
    period_start = serializers.DateTimeField(allow_null=True)
    period_end = serializers.DateTimeField(allow_null=True)
    paid_at = serializers.DateTimeField(allow_null=True)
    pdf_url = serializers.CharField(allow_blank=True)
    hosted_url = serializers.CharField(allow_blank=True)


class AllowanceRowSerializer(serializers.Serializer):
    limit = serializers.IntegerField(
        allow_null=True, help_text="null means unlimited."
    )
    unlimited = serializers.BooleanField()
    used = serializers.IntegerField()
    remaining = serializers.IntegerField(
        allow_null=True, help_text="null when unlimited."
    )


class AllowancesSerializer(serializers.Serializer):
    CHECKS = AllowanceRowSerializer(help_text="Resets each cycle.")
    SEATS = AllowanceRowSerializer()
    BANKS = AllowanceRowSerializer()
