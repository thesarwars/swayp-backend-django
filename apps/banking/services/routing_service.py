"""ABA routing number validation (E3-S9).

Powers the live "Valid – Chase Bank (ABA verified)" indicator on the vendor
ACH form. Two independent checks: the ABA checksum, which is arithmetic and
always available, and a bank-name lookup, which is best-effort.

The checksum proves the number is *well-formed*, not that the account exists —
account verification is the provider's job (BRD §3.3).
"""

from apps.banking.services.aba_directory import lookup_bank_name

ROUTING_LENGTH = 9

#: Positional weights for the ABA mod-10 checksum.
_WEIGHTS = (3, 7, 1, 3, 7, 1, 3, 7, 1)

#: The leading two digits encode the Federal Reserve district. 80-99 are
#: unassigned in the ABA scheme, and 00 never appears on a real institution.
_VALID_PREFIX_RANGES = (
    (1, 12),    # Federal Reserve routing symbols
    (21, 32),   # thrift institutions
    (61, 72),   # electronic transactions
    (80, 80),   # traveler's cheques
)


def normalize(routing_number):
    """Strip formatting. Returns digits only."""
    return "".join(ch for ch in str(routing_number or "") if ch.isdigit())


def has_valid_checksum(digits):
    """ABA mod-10: the weighted digit sum must be divisible by 10."""
    if len(digits) != ROUTING_LENGTH:
        return False

    total = sum(
        int(digit) * weight for digit, weight in zip(digits, _WEIGHTS)
    )

    return total % 10 == 0


def has_valid_prefix(digits):
    prefix = int(digits[:2])

    return any(low <= prefix <= high for low, high in _VALID_PREFIX_RANGES)


class RoutingValidationService:

    def validate(self, routing_number):
        """Describe a routing number without ever echoing it back."""
        digits = normalize(routing_number)

        # "abc" has no digits but was not empty: it is the wrong shape, not
        # missing, and saying "required" sent people looking for a blank field.
        if not str(routing_number or "").strip():
            return self._invalid("Routing number is required.")

        if len(digits) != ROUTING_LENGTH:
            return self._invalid(
                f"Routing number must be {ROUTING_LENGTH} digits."
            )

        if not has_valid_prefix(digits):
            return self._invalid(
                "Routing number does not begin with a valid ABA prefix."
            )

        if not has_valid_checksum(digits):
            return self._invalid("Routing number failed the ABA checksum.")

        bank_name = lookup_bank_name(digits)

        return {
            "valid": True,
            "bank_name": bank_name,
            # The checksum is verified arithmetic; the bank name is only as
            # good as the local directory, so the two are reported separately.
            "aba_verified": True,
            "bank_known": bank_name is not None,
            "message": (
                f"Valid – {bank_name} (ABA verified)"
                if bank_name
                else "Valid – ABA verified (bank not in directory)"
            ),
        }

    def _invalid(self, message):
        return {
            "valid": False,
            "bank_name": None,
            "aba_verified": False,
            "bank_known": False,
            "message": message,
        }
