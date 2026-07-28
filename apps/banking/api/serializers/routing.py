from rest_framework import serializers

from apps.banking.services.routing_service import ROUTING_LENGTH


class RoutingValidateSerializer(serializers.Serializer):
    """Write-only input — the routing number is never echoed back."""

    routing_number = serializers.CharField(
        write_only=True,
        max_length=32,
        trim_whitespace=True,
    )

    def validate_routing_number(self, value):
        if "*" in value:
            raise serializers.ValidationError(
                "Send the routing number, not a masked value."
            )

        return value


class RoutingValidationResultSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    bank_name = serializers.CharField(allow_null=True)
    aba_verified = serializers.BooleanField()
    bank_known = serializers.BooleanField()
    message = serializers.CharField()
