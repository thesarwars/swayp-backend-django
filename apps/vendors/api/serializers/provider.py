from rest_framework import serializers

from apps.providers.models import Provider


class ProviderSearchSerializer(serializers.ModelSerializer):

    category = serializers.CharField(source="category.name")

    class Meta:
        model = Provider

        fields = (
            "id",
            "provider_name",
            "provider_code",
            "category",
            "logo",
            "supports_auto_pay",
        )