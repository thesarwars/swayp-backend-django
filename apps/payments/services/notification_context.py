"""Deep-link context for payment-driven notifications (E8-S3).

One builder so every payment call-site files the same payload, instead of the
three different shapes the Notification.objects.create call-sites used to
carry. Key names are the vocabulary the templates and the reminder job share:
suffixed ids, ``vendor_name`` rather than ``vendor``.
"""


def payment_context(payment):
    occurrence = payment.bill_occurrence

    return {
        "payment_id": str(payment.id),
        "reference": payment.transaction_reference,
        "amount": str(payment.total),
        "vendor_name": payment.vendor.name if payment.vendor_id else "",
        "bill_id": str(occurrence.bill_id) if occurrence else "",
        "occurrence_id": str(occurrence.id) if occurrence else "",
    }
