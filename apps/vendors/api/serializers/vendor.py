from rest_framework import serializers

from apps.bill_categories.models import BillCategory
from apps.common.enums import VendorSource
from apps.vendors.models.vendor import Vendor


class VendorListSerializer(serializers.ModelSerializer):

    payment_rail = serializers.SerializerMethodField()

    class Meta:

        model = Vendor

        fields = (
            "id",
            "name",
            "logo",
            "business_type",
            "directory_verified",
            "payment_rail",
        )

    def get_payment_rail(self, obj):

        primary = obj.payment_methods.filter(
            is_primary=True
        ).first()

        if primary:
            return primary.method_type

        return None

from .vendor_payment_method import VendorPaymentMethodCreateSerializer, VendorPaymentMethodSerializer


class VendorDetailSerializer(serializers.ModelSerializer):

    payment_methods = VendorPaymentMethodSerializer(
        many=True,
        read_only=True,
    )

    class Meta:

        model = Vendor

        fields = (
            "id",
            "name",
            "category",
            "logo",
            "business_type",
            "notes",
            "source",
            "directory_verified",
            "late_fee_amount",
            "late_fee_grace_days",
            "payment_methods",
        )


class VendorUpdateSerializer(serializers.ModelSerializer):

    class Meta:

        model = Vendor

        fields = (
            "name",
            "category",
            "notes",
        )



class VendorCreateSerializer(serializers.Serializer):
    """
    Single endpoint for creating a Vendor.
    Supports three branches:
    - NETWORK
    - ACH
    - CHECK
    Business logic lives in VendorService.
    """

    name = serializers.CharField(max_length=150)
    category = serializers.PrimaryKeyRelatedField(
        queryset=BillCategory.objects.all()
    )
    source = serializers.ChoiceField(choices=VendorSource.choices)
    notes = serializers.CharField(required=False, allow_blank=True)

    payment_method = VendorPaymentMethodCreateSerializer()

    def validate(self, attrs):
        # Optional cross-field validation
        return attrs


class VendorSummarySerializer(serializers.Serializer):

    total = serializers.IntegerField()
    network = serializers.IntegerField()
    ach = serializers.IntegerField()
    check = serializers.IntegerField()
    check_total = serializers.DecimalField(max_digits=18,decimal_places=2,)