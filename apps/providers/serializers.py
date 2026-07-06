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

    categoryId = serializers.UUIDField()
    categoryName = serializers.CharField()

    providerName = serializers.CharField()
    providerCode = serializers.CharField()

    logo = serializers.URLField()

    description = serializers.CharField(
        allow_blank=True,
        allow_null=True,
    )

    country = serializers.CharField()

    supportsAutoPay = serializers.BooleanField()


class ProviderListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()

    message = serializers.CharField()

    data = ProviderSerializer(many=True)

    pagination = PaginationResponseSerializer()