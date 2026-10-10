"""Response envelopes for the payments API (PAY-2).

Documentation only: the views build these bodies; these serializers
describe them to OpenAPI. Every payments response is the standard envelope,
{ success, message, data }.
"""

from rest_framework import serializers

from apps.common.enums import PaymentStatus
from apps.payments.api.serializers.payment import (
    PaymentCreateResponseSerializer,
    PaymentSerializer,
    PaymentStageSerializer,
)


def envelope(name, data_serializer):
    """A { success, message, data } serializer around ``data_serializer``."""
    return type(
        name,
        (serializers.Serializer,),
        {
            "success": serializers.BooleanField(),
            "message": serializers.CharField(),
            "data": data_serializer,
        },
    )


class ReceiptBlockSerializer(serializers.Serializer):
    recipient = serializers.CharField(allow_null=True)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    funding_account = serializers.CharField(allow_null=True)
    estimated_arrival = serializers.DateField(allow_null=True)
    reference = serializers.CharField()
    paid_on = serializers.DateTimeField()


class FailureBlockSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True)
    detail = serializers.DictField()
    can_resolve = serializers.BooleanField()


class ProgressBlockSerializer(serializers.Serializer):
    completed = serializers.IntegerField()
    total = serializers.IntegerField()
    is_complete = serializers.BooleanField()


class PaymentStatusSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()
    reference = serializers.CharField()
    status = serializers.ChoiceField(choices=PaymentStatus.choices)
    stages = PaymentStageSerializer(many=True)
    progress = ProgressBlockSerializer()


class BatchStatusSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    status = serializers.ChoiceField(
        choices=PaymentStatus.choices,
        help_text="FAILED if any payment failed; SUCCESSFUL only if all did.",
    )
    total = serializers.DecimalField(max_digits=18, decimal_places=2)
    count = serializers.IntegerField()
    succeeded = serializers.IntegerField()
    failed = serializers.IntegerField()
    in_flight = serializers.IntegerField()
    payments = PaymentSerializer(many=True)


class BatchConfirmSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    payments = PaymentSerializer(many=True)
    replayed = serializers.BooleanField(
        help_text="True when the batch was already confirmed; nothing new."
    )


class BatchCancelSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    cancelled = PaymentSerializer(many=True)


PaymentCreateEnvelope = envelope(
    "PaymentCreateEnvelope", PaymentCreateResponseSerializer()
)
PaymentEnvelope = envelope("PaymentEnvelope", PaymentSerializer())
PaymentStatusEnvelope = envelope(
    "PaymentStatusEnvelope", PaymentStatusSerializer()
)
BatchStatusEnvelope = envelope("BatchStatusEnvelope", BatchStatusSerializer())
BatchConfirmEnvelope = envelope(
    "BatchConfirmEnvelope", BatchConfirmSerializer()
)
BatchCancelEnvelope = envelope("BatchCancelEnvelope", BatchCancelSerializer())
