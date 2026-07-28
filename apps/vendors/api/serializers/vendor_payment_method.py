from rest_framework import serializers

from apps.vendors.models import VendorPaymentMethod
from apps.common.enums import (
    VendorPaymentMethodType,
)


class VendorPaymentMethodSerializer(serializers.ModelSerializer):
    """
    Used for GET Payment Methods.
    """

    account_ref = serializers.SerializerMethodField()

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
        )

    def get_account_ref(self, obj):

        if obj.account_last4:
            return f"****{obj.account_last4}"

        return None


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