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


def rail_for_bill(bill):
    """The rail a bill's stored payment method implies.

    A bill with no saved method falls back to standard ACH, as it always
    has; such a payment has nowhere to go and fails at execution, so the
    quote reports no rail as available for it.
    """
    method = bill.payment_method

    if method is None:
        return PaymentRail.ACH_STANDARD

    return RAIL_BY_METHOD.get(method.method_type, PaymentRail.ACH_STANDARD)


def rails_for_bill(bill):
    """The rails the bill's saved method can receive; empty if it has none."""
    method = bill.payment_method

    if method is None:
        return ()

    return RAILS_BY_METHOD.get(method.method_type, ())
