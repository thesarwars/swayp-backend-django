from rest_framework import serializers

from apps.common.casing import snake_case_aliases

from apps.common.serializers import PaginationQuerySerializer




@snake_case_aliases
class PaymentSerializer(serializers.Serializer):
    id = serializers.UUIDField()

    # provider and category are both nullable on Payment (E6-S1), so these
    # have to tolerate None. Without allow_null they raise AttributeError
    # while rendering and turn the whole history page into a 500 — one
    # provider-less payment was enough to hide every other one.
    providerId = serializers.UUIDField(
        source="provider.id", allow_null=True, required=False, default=None
    )

    providerName = serializers.CharField(
        source="provider.provider_name",
        allow_null=True,
        required=False,
        default=None,
    )

    # PAY-3. providerName is the biller-directory provider, which a payment
    # to one of the user's own vendors does not have; these say who was
    # actually paid. camelCase like the rest of this body.
    vendorId = serializers.UUIDField(
        source="vendor_id", allow_null=True, required=False, default=None
    )
    vendorName = serializers.CharField(
        source="vendor.name", allow_null=True, required=False, default=None
    )
    billId = serializers.UUIDField(
        source="bill_occurrence.bill_id",
        allow_null=True,
        required=False,
        default=None,
    )
    occurrenceId = serializers.UUIDField(
        source="bill_occurrence_id",
        allow_null=True,
        required=False,
        default=None,
    )
    rail = serializers.CharField()
    estimatedArrival = serializers.DateField(
        source="estimated_arrival", allow_null=True
    )
    scheduledFor = serializers.DateField(
        source="scheduled_for", allow_null=True
    )
    replacedPaymentId = serializers.UUIDField(
        source="retry_of_id",
        allow_null=True,
        required=False,
        default=None,
        help_text="The failed payment this one retried, if any.",
    )

    categoryId = serializers.UUIDField(
        source="category.id", allow_null=True, required=False, default=None
    )

    categoryName = serializers.CharField(
        source="category.name",
        allow_null=True,
        required=False,
        default=None,
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



