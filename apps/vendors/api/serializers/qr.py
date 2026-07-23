from rest_framework import serializers


class QRDecodeSerializer(serializers.Serializer):
    payload = serializers.CharField(required=False,allow_blank=False)

    image = serializers.ImageField(required=False,)

    def validate(self, attrs):
        payload = attrs.get("payload")
        image = attrs.get("image")

        if not payload and not image:
            raise serializers.ValidationError(
                "Either payload or image must be provided."
            )

        if payload and image:
            raise serializers.ValidationError(
                "Provide either payload or image, not both."
            )

        return attrs