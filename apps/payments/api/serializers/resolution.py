"""Response shapes for failure detail and resolve (PAY-6)."""

from rest_framework import serializers

from apps.payments.api.serializers.payment import PaymentSerializer
from apps.payments.services.resolution_service import ACTIONS


class LateFeeSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    grace_days = serializers.IntegerField()
    days_remaining = serializers.IntegerField()
    applies = serializers.BooleanField(
        help_text="True once the grace period has passed."
    )


class PaymentFailureSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()
    transaction_reference = serializers.CharField()
    title = serializers.CharField(help_text="Display-ready heading.")
    explanation = serializers.CharField(help_text="Display-ready body.")
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    vendor_name = serializers.CharField(allow_null=True)
    failed_at = serializers.DateTimeField()
    failure_reason = serializers.CharField(
        allow_blank=True, help_text="Code, e.g. NSF, ACH_RETURN."
    )
    failure_detail = serializers.DictField()
    due_date = serializers.DateField(allow_null=True)
    days_overdue = serializers.IntegerField()
    late_fee = LateFeeSerializer(
        allow_null=True, help_text="Null when the vendor has no late fee."
    )
    available_actions = serializers.ListField(
        child=serializers.ChoiceField(choices=[(a, a) for a in ACTIONS])
    )


class PaymentFailureResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = PaymentFailureSerializer()


class ResolveResultSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=[(a, a) for a in ACTIONS])
    payment = PaymentSerializer(help_text="The new payment.")
    replaced_payment_id = serializers.UUIDField()
    authorization_text = serializers.CharField(
        help_text="Show it, then confirm the new payment with it."
    )
    requires_confirmation = serializers.BooleanField()


class ResolveResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = ResolveResultSerializer()
