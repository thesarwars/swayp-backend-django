"""Authorization wording shown at consent time (E6-S2 / E6-S3).

This is the **only** place a processor name is allowed to reach user-facing
text. NACHA requires the debiting party to be named, and the user has to be
told who actually moves the money — Swayp orchestrates, a licensed provider
executes.

The text is stored verbatim on the authorization, so it must be generated once
and reused, never re-derived at display time from data that may have changed.
"""

from apps.common.enums import PaymentProcessor, PaymentRail

#: The licensed party per rail (BRD §5).
PROCESSOR_BY_RAIL = {
    PaymentRail.ACH_STANDARD: PaymentProcessor.MOOV,
    PaymentRail.ACH_SAMEDAY: PaymentProcessor.MOOV,
    PaymentRail.NETWORK: PaymentProcessor.STRIPE,
    PaymentRail.CHECK: PaymentProcessor.LOB,
}

PROCESSOR_LEGAL_NAME = {
    PaymentProcessor.MOOV: "Moov Financial, Inc.",
    PaymentProcessor.STRIPE: "Stripe, Inc.",
    PaymentProcessor.LOB: "Lob.com, Inc.",
    PaymentProcessor.MOCK: "the Swayp test processor",
}


def processor_for_rail(rail):
    return PROCESSOR_BY_RAIL.get(rail, PaymentProcessor.MOCK)


def _money(amount):
    return f"${amount:,.2f}"


def _date(value):
    if value is None:
        return None

    return f"{value.strftime('%B')} {value.day}, {value.year}"


def _sentence(text):
    """End a sentence without doubling a period.

    Provider legal names end in "Inc." and this text is stored verbatim on a
    consent record, so "Moov Financial, Inc.." would be preserved forever.
    """
    text = text.rstrip()

    return text if text.endswith(".") else f"{text}."


def for_single(*, amount, vendor_name, funding_display, rail, processor,
               initiated_date=None, deadline_text=None):
    """Consent wording for one payment."""
    party = PROCESSOR_LEGAL_NAME.get(processor, str(processor))

    lines = [
        f"I authorize Swayp to debit {funding_display} for "
        f"{_money(amount)} and to pay {vendor_name}.",
        _sentence(
            f"This transfer will be executed by {party} over "
            f"{RAIL_LABEL.get(rail, rail)}"
        ),
    ]

    if initiated_date:
        lines.append(f"The debit will be initiated on {_date(initiated_date)}.")

    if deadline_text:
        lines.append(deadline_text)

    lines.append(
        "I understand this authorization remains in effect until the "
        "transfer completes or I cancel it."
    )

    return " ".join(lines)


def for_batch(*, total, count, funding_display, processors):
    """Consent wording covering a whole batch — one consent, many payments."""
    parties = sorted(
        {PROCESSOR_LEGAL_NAME.get(p, str(p)) for p in processors}
    )
    party_text = parties[0] if len(parties) == 1 else ", ".join(parties)

    return (
        f"I authorize Swayp to debit {funding_display} for a total of "
        f"{_money(total)} covering {count} bill"
        f"{'s' if count != 1 else ''}. "
        f"{_sentence(f'These transfers will be executed by {party_text}')} "
        "I understand this authorization covers every payment listed above "
        "and remains in effect until they complete or I cancel them."
    )


RAIL_LABEL = {
    PaymentRail.ACH_STANDARD: "the ACH network",
    PaymentRail.ACH_SAMEDAY: "same-day ACH",
    PaymentRail.NETWORK: "the biller network",
    PaymentRail.CHECK: "a mailed check",
}
