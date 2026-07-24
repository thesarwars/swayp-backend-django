from rest_framework import serializers

from rest_framework import serializers

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
    amount = serializers.DecimalField(max_digits=18,decimal_places=2,min_value=0.01)
    frequency = serializers.ChoiceField(choices=BillFrequency.choices)
    anchor_date = serializers.DateField()
    autopay_mode = serializers.ChoiceField(choices=AutopayMode.choices,default=AutopayMode.REMIND)
    payment_method = serializers.UUIDField(required=False,allow_null=True)
    source = serializers.ChoiceField(choices=BillSource.choices,default=BillSource.MANUAL)
    notes = serializers.CharField(required=False,allow_blank=True,default="")


class BillCategorySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    icon = serializers.CharField()
    color = serializers.CharField()
    displayOrder = serializers.IntegerField(source="display_order")
    

class BillCategoryListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = BillCategorySerializer(many=True)