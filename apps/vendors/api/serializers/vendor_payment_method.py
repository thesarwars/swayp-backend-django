from decimal import Decimal

from rest_framework import serializers

from apps.vendors.models import VendorPaymentMethod
from apps.vendors.services.payment_method_schedule import schedule_for_method
from apps.common.crypto import reject_masked_value
from apps.common.enums import (
    VendorPaymentMethodType,
)


class PaymentMethodScheduleQuerySerializer(serializers.Serializer):
    """Query params for the method-step lead-time computation (E3-S6)."""

    due_date = serializers.DateField(required=False)
    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )


class VendorPaymentMethodSerializer(serializers.ModelSerializer):
    """
    Used for GET Payment Methods.

    When the caller supplies ``?due_date=``, each row also carries a
    ``schedule`` block with the rail, lead time, initiation date and whether
    the method can still land by the due date.
    """

    account_ref = serializers.SerializerMethodField()
    schedule = serializers.SerializerMethodField()

    class Meta:
        model = VendorPaymentMethod

        fields = (
            "id",
            "method_type",
            "is_primary",
            "supports_same_day",
            "provider",
            "account_ref",
            "account_holder_name",
            "aba_bank_name",
            "payee_verified",
            "check_legal_name",
            "street",
            "line2",
            "city",
            "state",
            "zip_code",
            "check_memo",
            "schedule",
        )

    def get_account_ref(self, obj):

        if obj.account_last4:
            return f"****{obj.account_last4}"

        return None

    def get_schedule(self, obj):
        due_date = self.context.get("due_date")

        if not due_date:
            return None

        return schedule_for_method(obj, due_date)


class VendorPaymentMethodCreateSerializer(serializers.ModelSerializer):

    class Meta:

        model = VendorPaymentMethod

        exclude = (
            "id",
            "vendor",
            "created_at",
            "updated_at",
        )

        # Provider-determined facts, not client claims. `payee_verified` is
        # the BRD §3.3 vendor-account verification that drives the trust
        # badge, and `supports_same_day` is a network capability — a client
        # must not be able to assert either about itself.
        read_only_fields = (
            "payee_verified",
            "supports_same_day",
        )

    # Raw routing/account numbers never reach the backend — the client
    # tokenizes at Moov (Moov.js) and sends {provider_token, account_last4}.
    # Changing an account is therefore just sending a fresh token. What the
    # server must refuse is a masked echo (e.g. "****4821") being stored as a
    # real value (E1-S6 / BRD §3.4). On PATCH, an omitted field stays
    # unchanged (it never enters validated_data).
    def validate_provider_token(self, value):
        return reject_masked_value(value)

    def validate_account_last4(self, value):
        return reject_masked_value(value)

    def validate(self, attrs):

        method = attrs.get("method_type")

        if method == VendorPaymentMethodType.NETWORK:

            if not attrs.get("network_payee_ref"):

                raise serializers.ValidationError({
                    "network_payee_ref":
                        "This field is required."
                })

        elif method == VendorPaymentMethodType.ACH:

            required = [
                "provider",
                "provider_token",
                "account_last4",
                "account_holder_name",
            ]

            errors = {}

            for field in required:

                if not attrs.get(field):
                    errors[field] = "This field is required."

            if errors:
                raise serializers.ValidationError(errors)

        elif method == VendorPaymentMethodType.CHECK:

            required = [
                "check_legal_name",
                "street",
                "city",
                "state",
                "zip_code",
            ]

            errors = {}

            for field in required:

                if not attrs.get(field):
                    errors[field] = "This field is required."

            if errors:
                raise serializers.ValidationError(errors)

        return attrs