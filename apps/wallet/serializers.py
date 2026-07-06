from rest_framework import serializers


class WalletSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()

    balance = serializers.DecimalField(
        max_digits=20,
        decimal_places=2,
    )

    currency = serializers.CharField()

    status = serializers.CharField()

    updatedAt = serializers.DateTimeField(
        source="updated_at"
    )


class WalletSummaryResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = WalletSummarySerializer()