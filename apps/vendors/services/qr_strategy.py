from abc import ABC, abstractmethod

#: Field aliases recognised in a key=value payload. The real spec is still open
#: (PRD §10-Q6); these cover the shapes seen so far and anything else falls
#: through to the opaque branch.
_FIELD_ALIASES = {
    "vendor": "vendor_name",
    "vendor_name": "vendor_name",
    "name": "vendor_name",
    "biller": "vendor_name",
    "category": "category",
    "ref": "payment_ref",
    "payment_ref": "payment_ref",
    "account": "payment_ref",
    "amount": "amount",
    "due": "due_date",
    "due_date": "due_date",
}

#: Anything longer than this is not a QR payload we can make sense of.
MAX_PAYLOAD_LENGTH = 4096


class BaseQRParser(ABC):

    @abstractmethod
    def parse(self, payload: str):
        pass


class DefaultQRParser(BaseQRParser):
    """Provisional parser — the payload spec is still open (PRD §10-Q6).

    Two outcomes only: a payload we can read, or ``ValueError`` (which the view
    turns into a 422). It must never report a field as "detected" from input it
    did not actually understand — that is what let malformed payloads through
    as successful decodes.
    """

    def parse(self, payload: str):
        payload = (payload or "").strip()

        if not payload:
            raise ValueError("QR payload is empty.")

        if len(payload) > MAX_PAYLOAD_LENGTH:
            raise ValueError(
                f"QR payload exceeds {MAX_PAYLOAD_LENGTH} characters."
            )

        if not any(ch.isalnum() for ch in payload):
            raise ValueError(
                "QR payload is not readable — no recognisable content."
            )

        fields, provenance = self._parse_key_values(payload)

        if fields:
            return {
                "vendor_name": fields.get("vendor_name"),
                "category": fields.get("category"),
                "payment_ref": fields.get("payment_ref"),
                "amount": fields.get("amount"),
                "due_date": fields.get("due_date"),
                "provenance": provenance,
            }

        if not self._looks_like_reference(payload):
            raise ValueError("QR payload format is not recognised.")

        # Structurally unrecognised but plausibly a bare reference, so it is
        # surfaced as a guess rather than a detection.
        return {
            "vendor_name": None,
            "category": None,
            "payment_ref": payload,
            "amount": None,
            "due_date": None,
            "provenance": {
                "payment_ref": "guessed",
            },
        }

    def _parse_key_values(self, payload):
        """Read a ``k=v;k=v`` body, with an optional ``SCHEME:`` prefix."""
        body = payload

        if ":" in body and "=" in body:
            head, _, tail = body.partition(":")
            if "=" not in head:
                body = tail

        fields = {}
        provenance = {}

        for chunk in body.replace("&", ";").split(";"):
            key, separator, value = chunk.partition("=")

            if not separator:
                continue

            mapped = _FIELD_ALIASES.get(key.strip().lower())
            value = value.strip()

            if mapped and value:
                fields[mapped] = value
                provenance[mapped] = "detected"

        return fields, provenance

    def _looks_like_reference(self, payload):
        """A bare reference: single token, no whitespace, mostly alphanumeric."""
        if any(ch.isspace() for ch in payload):
            return False

        alphanumeric = sum(1 for ch in payload if ch.isalnum())

        return alphanumeric >= 4 and alphanumeric / len(payload) >= 0.6
