from rest_framework import serializers


class BalanceProjectionQuerySerializer(serializers.Serializer):
    """Query params for GET ai/balance-projection/ (E7-S3)."""

    account = serializers.UUIDField()
    date = serializers.DateField()


class BalanceProjectionSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    date = serializers.DateField()
    current_balance = serializers.DecimalField(max_digits=18, decimal_places=2)
    outflow_total = serializers.DecimalField(max_digits=18, decimal_places=2)
    projected_balance = serializers.DecimalField(
        max_digits=18, decimal_places=2
    )
    sufficient = serializers.BooleanField()
