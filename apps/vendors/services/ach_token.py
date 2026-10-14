"""Is an ACH provider_token one its provider could have issued? (web B9)

Any string used to pass, so the placeholder a client sent was stored as if
it were a bank account. Raw routing and account numbers never come to
Swayp (BRD §3.4): the client tokenizes them in the processor's SDK and
sends only the token, its provider and the last four digits. Kept out of
the serializer so processor names stay out of the API layer (E1-S4).
"""

import re

from django.conf import settings

#: What each provider's bank-account tokens look like.
TOKEN_SHAPES = {
    "STRIPE": re.compile(r"^(btok|ba|pm|src)_[A-Za-z0-9]+$"),
}


def token_problem(provider, token):
    """None if acceptable, else a message for the field it concerns, as
    (field, message)."""
    if provider == "MOCK":
        if getattr(settings, "MONEY_MOVEMENT_PROVIDER", "mock") != "mock":
            return (
                "provider",
                "Test tokens are refused: this server moves real money.",
            )

        return None

    shape = TOKEN_SHAPES.get(provider)

    if shape is not None and token and not shape.match(token):
        return ("provider_token", "Not a bank token from this provider.")

    return None
