from rest_framework import serializers


class ConsentInputSerializer(serializers.Serializer):
    """Optional exact consent text shown to the user (E7-S1)."""

    consent_text = serializers.CharField(required=False, allow_blank=True)


class ConsentSerializer(serializers.Serializer):
    consented_at = serializers.DateTimeField()
    revoked_at = serializers.DateTimeField(allow_null=True)
    is_live = serializers.BooleanField()
