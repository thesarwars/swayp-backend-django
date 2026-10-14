from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.vendors.models import VendorPaymentMethod
from apps.vendors.services.payment_method_schedule import schedule_for_method
from apps.common.crypto import reject_masked_value
from apps.common.enums import (
    PaymentRail,
    VendorPaymentMethodType,
)


class PaymentMethodScheduleSerializer(serializers.Serializer):
    """When a payment by this method must start to land by due_date."""

    rail = serializers.ChoiceField(choices=PaymentRail.choices)
    due_date = serializers.DateField()
    lead_business_days = serializers.IntegerField()
    initiate_by = serializers.DateField()
    estimated_arrival = serializers.DateField()
    can_meet_due_date = serializers.BooleanField()


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
            # VEND-9: checking or savings, and the biller-network reference.
            "account_type",
            "account_holder_name",
            "network_payee_ref",
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

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_account_ref(self, obj):

        if obj.account_last4:
            return f"****{obj.account_last4}"

        return None

    @extend_schema_field(
        PaymentMethodScheduleSerializer(
            allow_null=True,
            help_text="Only when the request passes due_date; else null.",
        )
    )
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

    # Raw routing/account numbers never reach the backend (BRD §3.4): the
    # client tokenizes them in the money-movement provider's SDK and sends
    # {provider, provider_token, account_last4}. The token must be one that
    # provider could have issued (web B9); any string used to pass, so a
    # placeholder was stored as a bank account. A masked echo ("****4821")
    # is refused as a real value (E1-S6). On PATCH, an omitted field stays
    # unchanged (it never enters validated_data).
    def validate_provider_token(self, value):
        return reject_masked_value(value)

    def validate_account_last4(self, value):
        return reject_masked_value(value)

    def _validate_ach(self, attrs):
        from apps.vendors.services.ach_token import token_problem

        errors = {}

        for field in (
            "provider", "provider_token", "account_last4", "account_holder_name",
        ):
            if not attrs.get(field):
                errors[field] = "This field is required."

        problem = token_problem(
            attrs.get("provider"), attrs.get("provider_token")
        )

        if problem:
            field, message = problem
            errors.setdefault(field, message)

        if errors:
            raise serializers.ValidationError(errors)

    def validate(self, attrs):

        method = attrs.get("method_type")

        if method == VendorPaymentMethodType.NETWORK:

            if not attrs.get("network_payee_ref"):

                raise serializers.ValidationError({
                    "network_payee_ref":
                        "This field is required."
                })

        elif method == VendorPaymentMethodType.ACH:

            self._validate_ach(attrs)

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