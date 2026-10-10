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


class DirectoryMatchSerializer(serializers.Serializer):
    id = serializers.CharField()
    provider_name = serializers.CharField()
    category = serializers.CharField(allow_null=True)
    supports_auto_pay = serializers.BooleanField()
    verified = serializers.BooleanField()


class VendorQRDecodeResponseSerializer(serializers.Serializer):
    """Bare (no envelope), unlike bills/qr/decode."""

    vendor_name = serializers.CharField(allow_null=True)
    category = serializers.CharField(allow_null=True)
    payment_ref = serializers.CharField(allow_null=True)
    amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, allow_null=True
    )
    due_date = serializers.DateField(allow_null=True)
    provenance = serializers.DictField(
        child=serializers.CharField(),
        help_text="For each field read from the QR, where it came from.",
    )
    directory_match = DirectoryMatchSerializer(
        allow_null=True, help_text="A biller-directory entry by that name."
    )
