"""Request and response for the autopay authorization preview (BILLS-3)."""

from decimal import Decimal

from rest_framework import serializers

from apps.common.enums import BillFrequency, BillType


class AutopayAuthorizationPreviewSerializer(serializers.Serializer):
    """The terms the user is about to authorize: the add-bill wizard's
    choices, or an existing bill's terms after an edit."""

    vendor = serializers.UUIDField()
    amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, min_value=Decimal("0.01")
    )
    bill_type = serializers.ChoiceField(
        choices=BillType.choices, default=BillType.FIXED
    )
    frequency = serializers.ChoiceField(choices=BillFrequency.choices)
    anchor_date = serializers.DateField()
    payment_method = serializers.UUIDField(required=False, allow_null=True)


class AutopayAuthorizationSerializer(serializers.Serializer):
    authorization_text = serializers.CharField(
        help_text=(
            "Show this, and send it back verbatim as "
            "autopay_consent.authorization_text."
        )
    )
    funding_account = serializers.CharField(
        allow_null=True,
        help_text="The account named in the text; null when none is linked.",
    )


class AutopayAuthorizationResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AutopayAuthorizationSerializer()
