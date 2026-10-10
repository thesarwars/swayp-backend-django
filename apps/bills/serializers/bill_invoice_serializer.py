"""Bill invoice (E4-S7): the modal's fields, built by InvoiceService."""

from rest_framework import serializers

from apps.common.enums import (
    AutopayMode,
    BillFrequency,
    BillOccurrenceStatus,
    BillType,
    VendorPaymentMethodType,
)


class BillInvoiceSerializer(serializers.Serializer):
    bill_id = serializers.UUIDField()
    occurrence_id = serializers.UUIDField(
        allow_null=True, help_text="The next open due date; null if none."
    )
    vendor_name = serializers.CharField()
    vendor_logo = serializers.CharField(allow_blank=True, allow_null=True)
    category = serializers.CharField()
    bill_type = serializers.ChoiceField(choices=BillType.choices)
    frequency = serializers.ChoiceField(choices=BillFrequency.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    due_date = serializers.DateField(allow_null=True)
    status = serializers.ChoiceField(
        choices=BillOccurrenceStatus.choices, allow_null=True
    )
    autopay_mode = serializers.ChoiceField(choices=AutopayMode.choices)
    payment_method = serializers.ChoiceField(
        choices=VendorPaymentMethodType.choices, allow_null=True
    )
    notes = serializers.CharField(allow_blank=True, allow_null=True)
    payment_reference = serializers.CharField()
    qr_payload = serializers.CharField(
        help_text="What the invoice QR encodes."
    )
