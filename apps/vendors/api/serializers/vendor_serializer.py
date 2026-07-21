from rest_framework import serializers
from apps.vendors.models.bank import VendorMailingDetail
from apps.vendors.models.vendor import VendorBankDetail, Vendor



class VendorSerializer(serializers.ModelSerializer):

    class Meta:
        model = Vendor
        fields = "__all__"
        read_only_fields = (
            "id",
            "created_at",
            "updated_at",
        )


class VendorListSerializer(serializers.ModelSerializer):

    class Meta:
        model = Vendor

        fields = (
            "id",
            "name",
            "business_type",
            "payment_method",
            "is_verified",
        )


class VendorCreateSerializer(serializers.ModelSerializer):

    class Meta:
        model = Vendor

        exclude = (
            "created_at",
            "updated_at",
        )

    def create(self, validated_data):

        validated_data["user"] = self.context["request"].user

        return super().create(validated_data)


class VendorDashboardSerializer(serializers.Serializer):

    total_vendor = serializers.IntegerField()

    stripe = serializers.IntegerField()

    ach = serializers.IntegerField()

    check = serializers.DecimalField(
        max_digits=12,
        decimal_places=2
    )