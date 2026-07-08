from rest_framework import serializers

from apps.common.serializers import PaginationQuerySerializer




class PaymentSerializer(serializers.Serializer):
    id = serializers.UUIDField()

    providerId = serializers.UUIDField(
        source="provider.id"
    )

    providerName = serializers.CharField(
        source="provider.provider_name"
    )

    categoryId = serializers.UUIDField(
        source="category.id"
    )

    categoryName = serializers.CharField(
        source="category.name"
    )

    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    fee = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    total = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
    )

    currency = serializers.CharField()

    status = serializers.CharField()

    transactionReference = serializers.CharField(
        source="transaction_reference"
    )

    providerReference = serializers.CharField(
        source="provider_reference"
    )

    paymentMethod = serializers.CharField(
        source="payment_method"
    )

    createdAt = serializers.DateTimeField(
        source="created_at"
    )

    updatedAt = serializers.DateTimeField(
        source="updated_at"
    )


class PaymentHistoryResponseSerializer(
    serializers.Serializer
):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = PaymentSerializer(many=True)


class PaymentHistoryQuerySerializer(
    PaginationQuerySerializer
):
    status = serializers.CharField(
        required=False,
    )

    providerId = serializers.UUIDField(
        required=False,
    )

    categoryId = serializers.UUIDField(
        required=False,
    )

    fromDate = serializers.DateField(
        required=False,
    )

    toDate = serializers.DateField(
        required=False,
    )

    search = serializers.CharField(
        required=False,
        max_length=100,
    )


class CreatePaymentSerializer(serializers.Serializer):
    providerId = serializers.UUIDField()

    categoryId = serializers.UUIDField()

    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=0.01,
    )

    paymentMethod = serializers.CharField(
        max_length=50,
    )


class CreatePaymentResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = PaymentSerializer()


class PaymentStatusUpdateSerializer(
    serializers.Serializer,
):
    status = serializers.ChoiceField(
        choices=[
            "PROCESSING",
            "SUCCESSFUL",
            "FAILED",
            "CANCELLED",
            "REFUNDED",
        ]
    )


class PaymentStatusUpdateResponseSerializer(
    serializers.Serializer,
):
    success = serializers.BooleanField()
    message = serializers.CharField()



