from decimal import Decimal

from rest_framework import serializers

from apps.bills.models.bill import Bill
from apps.common.enums import (
    AutopayMode,
    BillFrequency,
    BillSource,
    BillType,
)


class BillCreateSerializer(serializers.Serializer):
    vendor = serializers.UUIDField()
    category = serializers.UUIDField()
    bill_type = serializers.ChoiceField(choices=BillType.choices,default=BillType.FIXED)
    amount = serializers.DecimalField(max_digits=18,decimal_places=2,min_value=Decimal("0.01"))
    frequency = serializers.ChoiceField(choices=BillFrequency.choices)
    anchor_date = serializers.DateField()
    autopay_mode = serializers.ChoiceField(choices=AutopayMode.choices,default=AutopayMode.REMIND)
    payment_method = serializers.UUIDField(required=False,allow_null=True)
    source = serializers.ChoiceField(choices=BillSource.choices,default=BillSource.MANUAL)
    notes = serializers.CharField(required=False,allow_blank=True,default="")


class BillListSerializer(serializers.ModelSerializer):
    vendor = serializers.CharField(source="vendor.name")
    category = serializers.CharField(source="category.name")
    payment_method = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = (
            "id",
            "vendor",
            "category",
            "amount",
            "frequency",
            "anchor_date",
            "autopay_mode",
            "bill_type",
            "payment_method",
        )

    def get_payment_method(self, obj):
        if obj.payment_method:
            return obj.payment_method.method_type 
        return None


class BillUpdateSerializer(serializers.Serializer):
    category = serializers.UUIDField(required=False)

    bill_type = serializers.ChoiceField(
        choices=BillType.choices,
        required=False,
    )

    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )

    frequency = serializers.ChoiceField(
        choices=BillFrequency.choices,
        required=False,
    )

    anchor_date = serializers.DateField(
        required=False,
    )

    autopay_mode = serializers.ChoiceField(choices=AutopayMode.choices,required=False)
    payment_method = serializers.UUIDField(required=False,allow_null=True)
    source = serializers.ChoiceField(choices=BillSource.choices,required=False)
    notes = serializers.CharField(required=False,allow_blank=True)