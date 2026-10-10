"""Review summary echoed after the create wizard (E4-S3).

Screen 834:4324 confirms the bill back to the user in words — "Swayp will pay
WeWork $3,200.00 on January 1, 2027". The sentence is built server-side so the
wording of an autopay commitment matches what was authorized, and the parts are
returned alongside it so a client can lay it out differently.
"""

from rest_framework import serializers

from apps.common.enums import (
    AutopayMode,
    BillFrequency,
    BillType,
    VendorPaymentMethodType,
)


def _format_amount(amount):
    return f"${amount:,.2f}"


def _format_date(value):
    if value is None:
        return None

    # "January 1, 2027" — %-d/%#d are platform-specific, so strip by hand.
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def build_review(bill, next_due_date=None, autopay_authorized=False):
    """Assemble the review payload for a freshly created or edited bill."""
    vendor_name = bill.vendor.name
    amount = _format_amount(bill.amount)
    due_text = _format_date(next_due_date)

    if bill.autopay_mode == AutopayMode.AUTO:
        summary = (
            f"Swayp will pay {vendor_name} {amount} on {due_text}."
            if due_text
            else f"Swayp will pay {vendor_name} {amount} automatically."
        )
    else:
        summary = (
            f"We'll remind you to pay {vendor_name} {amount} on {due_text}."
            if due_text
            else f"We'll remind you to pay {vendor_name} {amount}."
        )

    return {
        "id": bill.id,
        "vendor": vendor_name,
        "category": bill.category.name,
        "amount": bill.amount,
        "frequency": bill.frequency,
        "bill_type": bill.bill_type,
        "autopay_mode": bill.autopay_mode,
        "autopay_authorized": autopay_authorized,
        "payment_method": (
            bill.payment_method.method_type if bill.payment_method else None
        ),
        "next_due_date": next_due_date,
        "summary": summary,
    }


class BillReviewSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    vendor = serializers.CharField(help_text="The vendor's name.")
    category = serializers.CharField(help_text="The category's name.")
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    # ChoiceFields so OpenAPI publishes the enums (BILLS-1); output only.
    frequency = serializers.ChoiceField(choices=BillFrequency.choices)
    bill_type = serializers.ChoiceField(choices=BillType.choices)
    autopay_mode = serializers.ChoiceField(choices=AutopayMode.choices)
    autopay_authorized = serializers.BooleanField()
    payment_method = serializers.ChoiceField(
        choices=VendorPaymentMethodType.choices,
        allow_null=True,
        help_text="The method's type, or null when the bill has none.",
    )
    next_due_date = serializers.DateField(allow_null=True)
    summary = serializers.CharField(
        help_text='E.g. "Swayp will pay WeWork $3,200.00 on November 1, 2026."'
    )


class BillReviewResponseSerializer(serializers.Serializer):
    """Create (201) and update (200) both answer with the review."""

    success = serializers.BooleanField()
    message = serializers.CharField()
    data = BillReviewSerializer()
