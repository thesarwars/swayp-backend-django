"""Local ABA routing → bank name directory (E3-S9).

A small seed set of major US institutions so the form can show a bank name
without a network call. It is deliberately incomplete: an unknown routing
number that passes the checksum is still reported valid, just without a name.

Provider-ready — swapping in a full FedACH directory or a lookup API means
replacing ``lookup_bank_name`` alone.
"""

_DIRECTORY = {
    "021000021": "JPMorgan Chase Bank",
    "021000089": "Citibank",
    "026009593": "Bank of America",
    "121000248": "Wells Fargo Bank",
    "121042882": "Wells Fargo Bank",
    "031101279": "Bank of America",
    "011401533": "KeyBank",
    "071000013": "JPMorgan Chase Bank",
    "111000025": "Bank of America",
    "122105155": "Wells Fargo Bank",
    "125008547": "U.S. Bank",
    "091000019": "U.S. Bank",
    "061000104": "SunTrust / Truist",
    "053000196": "Truist Bank",
    "322271627": "JPMorgan Chase Bank",
    "021200025": "TD Bank",
    "031201360": "TD Bank",
    "254070116": "Capital One",
    "051405515": "Capital One",
    "256074974": "Navy Federal Credit Union",
    "121140399": "Silicon Valley Bank",
    "084009519": "Mercury / Choice Financial",
}


def lookup_bank_name(routing_number):
    """Bank name for a routing number, or ``None`` if it is not known here."""
    return _DIRECTORY.get(routing_number)


def directory_size():
    return len(_DIRECTORY)
