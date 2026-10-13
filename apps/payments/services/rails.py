"""Which rails a bill can be paid on (PAY-5).

Money goes to the bill's saved payment method: execution sends it to that
method's token. So the rail has to suit the method: an ACH account takes
standard or same-day ACH, a mailing address takes a check, a biller-network
payee takes the network. A rail the method cannot receive would fail at the
processor, after the user had confirmed.

Kept apart from autopay_service because that module imports the create
service, and the create service needs these too.
"""

from apps.common.enums import PaymentRail

#: The default rail per stored payment-method type.
RAIL_BY_METHOD = {
    "ACH": PaymentRail.ACH_STANDARD,
    "NETWORK": PaymentRail.NETWORK,
    "CHECK": PaymentRail.CHECK,
}

#: Every rail a method type can receive.
RAILS_BY_METHOD = {
    "ACH": (PaymentRail.ACH_STANDARD, PaymentRail.ACH_SAMEDAY),
    "NETWORK": (PaymentRail.NETWORK,),
    "CHECK": (PaymentRail.CHECK,),
}


def method_for_bill(bill):
    """The payment method a bill is actually paid by.

    Its own when it names one, otherwise its vendor's primary. ``Bill``'s
    ``payment_method`` is an override — for a vendor with several methods, or
    a one-off — not a requirement, because "primary" already means the method
    to use unless told otherwise. It is how the vendor list derives the rail
    it shows per vendor, and the add-bill screens have no method step.

    Without the fallback every bill the bank scan imported was permanently
    unpayable. The importer creates a vendor it has no routing details for,
    so the bill was stored with no method and the quote reported every rail
    unavailable — and adding ACH details to that vendor afterwards did not
    reach the bills already imported against it, because nothing re-pointed
    them. Resolving here rather than copying the id onto the bill at import
    is what makes those bills payable the moment the vendor can be paid.
    """
    if bill.payment_method_id:
        return bill.payment_method

    vendor = bill.vendor

    return vendor.primary_payment_method if vendor is not None else None


def rail_for_bill(bill):
    """The rail a bill's effective payment method implies.

    A bill whose vendor has no method at all falls back to standard ACH, as
    it always has; such a payment has nowhere to go and fails at execution,
    so the quote reports no rail as available for it.
    """
    method = method_for_bill(bill)

    if method is None:
        return PaymentRail.ACH_STANDARD

    return RAIL_BY_METHOD.get(method.method_type, PaymentRail.ACH_STANDARD)


def rails_for_bill(bill):
    """The rails the bill's effective method can receive; empty if none."""
    method = method_for_bill(bill)

    if method is None:
        return ()

    return RAILS_BY_METHOD.get(method.method_type, ())
