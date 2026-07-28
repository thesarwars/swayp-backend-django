from decimal import Decimal

from rest_framework import serializers


class CashContextInputSerializer(serializers.Serializer):
    """The pending payment Flo is asked to reason about (E7-S2)."""

    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    funding_account_id = serializers.UUIDField(required=False)


class _NextBillSerializer(serializers.Serializer):
    vendor = serializers.CharField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    due_date = serializers.DateField()


class _FiguresSerializer(serializers.Serializer):
    balance_now = serializers.DecimalField(max_digits=18, decimal_places=2)
    balance_after = serializers.DecimalField(max_digits=18, decimal_places=2)
    # When the bank last reported the balance, so the client can caveat a
    # figure the provider could not refresh.
    balance_as_of = serializers.DateTimeField(allow_null=True)
    upcoming_count = serializers.IntegerField()
    upcoming_total = serializers.DecimalField(max_digits=18, decimal_places=2)
    next_bill = _NextBillSerializer(allow_null=True)


class CashContextSerializer(serializers.Serializer):
    text = serializers.CharField()
    figures = _FiguresSerializer()
