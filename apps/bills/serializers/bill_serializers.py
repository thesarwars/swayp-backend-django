from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bills.models.bill import Bill
from apps.common.enums import (
    AutopayMode,
    BillFrequency,
    BillSource,
    BillType,
    VendorPaymentMethodType,
)


class AutopayConsentSerializer(serializers.Serializer):
    """The consent captured when a user switches a bill to autopay.

    ``authorization_text`` is the exact wording shown at the time, not a
    template id — a standing authorization has to reproduce what the user
    actually read (E4-S3).
    """

    accepted = serializers.BooleanField()
    authorization_text = serializers.CharField(
        max_length=5000,
        allow_blank=False,
        trim_whitespace=True,
    )


def validate_autopay_consent(autopay_mode, consent):
    """AUTO requires accepted consent; REMIND must not carry one."""
    if autopay_mode == AutopayMode.AUTO:
        if not consent or not consent.get("accepted"):
            raise serializers.ValidationError(
                {
                    "autopay_consent": (
                        "Autopay requires an accepted authorization with the "
                        "text shown to the user."
                    )
                }
            )

    elif consent:
        raise serializers.ValidationError(
            {
                "autopay_consent": (
                    "Authorization is only captured when autopay_mode is AUTO."
                )
            }
        )


class BillCreateSerializer(serializers.Serializer):
    vendor = serializers.UUIDField()
    category = serializers.UUIDField()
    bill_type = serializers.ChoiceField(choices=BillType.choices,default=BillType.FIXED)
    amount = serializers.DecimalField(max_digits=18,decimal_places=2,min_value=Decimal("0.01"))
    frequency = serializers.ChoiceField(choices=BillFrequency.choices)
    anchor_date = serializers.DateField()
    autopay_mode = serializers.ChoiceField(choices=AutopayMode.choices,default=AutopayMode.REMIND)
    payment_method = serializers.UUIDField(required=False,allow_null=True)
    source = serializers.ChoiceField(choices=BillSource.choices,default=BillSource.MANUAL)
    # Capped (BILLS-11): it was unlimited, and it renders on the detail
    # screen and the invoice.
    notes = serializers.CharField(
        max_length=2000, required=False, allow_blank=True, default=""
    )
    payment_ref = serializers.CharField(
        max_length=100, required=False, allow_blank=True, default=""
    )
    autopay_consent = AutopayConsentSerializer(required=False)

    def validate(self, attrs):
        validate_autopay_consent(
            attrs.get("autopay_mode"),
            attrs.get("autopay_consent"),
        )

        return attrs


class BillListSerializer(serializers.ModelSerializer):
    # vendor and category are NAMES here, while create and update take ids
    # under the same keys. Kept for existing clients; read the explicit
    # *_id / *_name pairs (web C9).
    vendor = serializers.CharField(source="vendor.name")
    category = serializers.CharField(source="category.name")
    vendor_id = serializers.UUIDField(read_only=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    category_id = serializers.UUIDField(read_only=True)
    category_name = serializers.CharField(
        source="category.name", read_only=True
    )
    payment_method = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = (
            "id",
            "vendor",
            "category",
            "vendor_id",
            "vendor_name",
            "category_id",
            "category_name",
            "amount",
            "frequency",
            "anchor_date",
            "autopay_mode",
            "bill_type",
            "payment_method",
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


class BillUpdateSerializer(serializers.Serializer):
    category = serializers.UUIDField(required=False)

    bill_type = serializers.ChoiceField(
        choices=BillType.choices,
        required=False,
    )

    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )

    frequency = serializers.ChoiceField(
        choices=BillFrequency.choices,
        required=False,
    )

    anchor_date = serializers.DateField(
        required=False,
    )

    autopay_mode = serializers.ChoiceField(choices=AutopayMode.choices,required=False)
    payment_method = serializers.UUIDField(required=False,allow_null=True)
    source = serializers.ChoiceField(choices=BillSource.choices,required=False)
    notes = serializers.CharField(
        max_length=2000, required=False, allow_blank=True
    )
    payment_ref = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    autopay_consent = AutopayConsentSerializer(required=False)

    def validate(self, attrs):
        # When the request sets the mode, consent must match it. Without a
        # mode, consent is how an autopay bill re-authorizes changed terms
        # (BILLS-4); the service decides whether the bill needs it, because
        # only it knows the bill's current mode.
        if "autopay_mode" in attrs:
            validate_autopay_consent(
                attrs["autopay_mode"],
                attrs.get("autopay_consent"),
            )

        elif attrs.get("autopay_consent") and not attrs[
            "autopay_consent"
        ].get("accepted"):
            raise serializers.ValidationError(
                {"autopay_consent": "The authorization must be accepted."}
            )

        return attrs