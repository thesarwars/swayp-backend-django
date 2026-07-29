"""Copy for the typed events (E8-S3).

Keyed by NotificationType so notify(user, type, context) can derive its own
wording — payments and the reminder job supply facts, not sentences.

The context key vocabulary is fixed and shared with E8-S4: bill_id,
occurrence_id, payment_id, reference, vendor_name, amount, due_date, reason,
late_fee_amount, grace_days, days_remaining. Suffixed names throughout, to
match the deep-link keys the epic already names.
"""

from apps.common.enums import NotificationType

#: type -> (title template, body template, required context keys).
TEMPLATES = {
    NotificationType.BILL_DUE: (
        "{vendor_name} is due",
        "{vendor_name} for {amount} was due on {due_date}. Approve it to pay.",
        ("vendor_name", "amount", "due_date"),
    ),
    NotificationType.PAYMENT_FAILED: (
        "Payment failed",
        "Payment {reference} failed: {reason}. The bill is outstanding again.",
        ("reference", "reason"),
    ),
    NotificationType.PAYMENT_REVERSED: (
        "Payment returned",
        "{reference} was returned by the bank. The bill is outstanding again.",
        ("reference",),
    ),
    # Present tense, deliberately. This is emitted from AutopayService._pay at
    # the moment the payment is created — the transfer itself runs from an
    # on_commit callback afterwards and can still come back NSF seconds later,
    # so "paid"/"sent" would be a settlement claim on a PROCESSING payment.
    # Same rule as execution_service._succeed staying off PAYMENT_ARRIVED: the
    # notification may only claim what has actually happened by the time it is
    # written. The landing is reported separately, by the PAYMENT/
    # PAYMENT_ARRIVED and PAYMENT_FAILED events.
    NotificationType.AUTOPAY_EXECUTED: (
        "Autopay started for {vendor_name}",
        "Autopay is sending {amount} to {vendor_name} for the bill due "
        "{due_date}. We'll let you know when it lands.",
        ("vendor_name", "amount", "due_date"),
    ),
    NotificationType.PAYMENT_ARRIVED: (
        "Payment completed",
        "{reference} to {vendor_name} completed.",
        ("reference", "vendor_name"),
    ),
    NotificationType.LATE_FEE_WARNING: (
        "{vendor_name} late fee in {days_remaining} days",
        "No late fee yet on {vendor_name}. You have {days_remaining} day(s) "
        "before a {late_fee_amount} late fee applies.",
        ("vendor_name", "days_remaining", "late_fee_amount"),
    ),
}


def render(type, context, *, title=None, message=None):
    """Resolve one event's copy, or raise.

    A type either has a template — in which case the copy is single-sourced
    here and an override is refused — or it has none, in which case the caller
    must supply both strings. The generic SYSTEM/PAYMENT/PROMOTION/SECURITY
    members are the second case: they carry different wording per call-site,
    so no type -> template mapping can express them.

    Every failure here is a developer error, and all of them raise. A
    notification that reaches a user reading "Payment {reference} failed" is
    worse than a red test.
    """
    key = str(type)

    if key not in NotificationType.values:
        raise ValueError(f"Unknown notification type {key!r}.")

    template = TEMPLATES.get(key)

    if template is None:
        if title is None or message is None:
            raise ValueError(
                f"{key} has no template, so title and message are required."
            )

        return title, message

    if title is not None or message is not None:
        raise ValueError(
            f"{key} is templated; passing title or message would fork its "
            "copy across call-sites."
        )

    title_template, message_template, required = template
    missing = [name for name in required if name not in context]

    if missing:
        raise ValueError(
            f"{key} needs context keys {sorted(missing)}."
        )

    return (
        title_template.format(**context),
        message_template.format(**context),
    )
