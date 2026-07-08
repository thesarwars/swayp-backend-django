from rest_framework import serializers

from apps.common.serializers import PaginationQuerySerializer


class PaymentTrackingSerializer(serializers.Serializer):
    paymentId = serializers.UUIDField(
        source="payment.id",
    )

    status = serializers.CharField()

    provider = serializers.CharField(
        source="payment.provider.provider_name",
    )

    amount = serializers.DecimalField(
        source="payment.amount",
        max_digits=18,
        decimal_places=2,
    )

    reference = serializers.CharField(
        source="payment.transaction_reference",
    )

    createdAt = serializers.DateTimeField(
        source="payment.created_at",
    )

    updatedAt = serializers.DateTimeField(
        source="updated_at",
    )

    estimatedCompletion = serializers.DateTimeField(
        source="estimated_completion",
        allow_null=True,
    )


class PaymentTrackingResponseSerializer(
    serializers.Serializer,
):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = PaymentTrackingSerializer(
        many=True,
    )


class PaymentTrackingQuerySerializer(
    PaginationQuerySerializer,
):
    pass