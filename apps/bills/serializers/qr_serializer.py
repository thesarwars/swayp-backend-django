"""Bill QR decode response (BILLS-2)."""

from rest_framework import serializers


class BillQRPrefillSerializer(serializers.Serializer):
    vendor_id = serializers.UUIDField(
        allow_null=True,
        help_text="The account's saved vendor with this name; null if none.",
    )
    vendor_name = serializers.CharField(allow_null=True)
    category_id = serializers.UUIDField(
        allow_null=True,
        help_text=(
            "The active category the QR names, else the matched vendor's "
            "category; null if neither."
        ),
    )
    category = serializers.CharField(
        allow_null=True, help_text="The category name as the QR spells it."
    )
    amount = serializers.DecimalField(
        max_digits=18, decimal_places=2, allow_null=True
    )
    due_date = serializers.DateField(allow_null=True)
    payment_ref = serializers.CharField(allow_null=True)
    provenance = serializers.DictField(
        child=serializers.CharField(),
        help_text="For each field read from the QR, where it came from.",
    )


class BillQRDecodeResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = BillQRPrefillSerializer()
