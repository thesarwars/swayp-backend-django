from rest_framework import serializers

from apps.common.serializers import (
    PaginationQuerySerializer,
    PaginationResponseSerializer,
)


class ProviderQuerySerializer(PaginationQuerySerializer):
    categoryId = serializers.UUIDField(required=False)
    search = serializers.CharField(required=False, allow_blank=True)


class ProviderSearchQuerySerializer(PaginationQuerySerializer):
    q = serializers.CharField()


class ProviderSerializer(serializers.Serializer):
    id = serializers.UUIDField()

    categoryId = serializers.UUIDField(source="category.id")
    categoryName = serializers.CharField(source="category.name")

    providerName = serializers.CharField(source="provider_name")
    providerCode = serializers.CharField(source="provider_code")

    logo = serializers.URLField()

    description = serializers.CharField()

    country = serializers.CharField()

    supportsAutoPay = serializers.BooleanField(source="supports_auto_pay")


class ProviderListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = ProviderSerializer(many=True)
    pagination = PaginationResponseSerializer()