"""Bill QR decode (E4-S7).

Delegates to the vendor QR parser. The acceptance criterion is explicitly
"shared parser, one code path" — this module adds bill-shaped interpretation
on top of a single decode implementation, it does not re-parse anything.
"""

from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_date

from apps.vendors.services.qr_decoder import QRDecodeService


class BillQRService:

    def __init__(self):
        self.decoder = QRDecodeService()

    def decode(self, *, payload=None, image=None):
        """Decode a QR into bill-wizard prefill fields.

        Raises ValueError for unreadable input, which the view maps to 422.
        """
        if payload:
            result = self.decoder.decode_payload(payload)
        else:
            result = self.decoder.decode_image(image)

        return self._as_bill_prefill(result)

    def _as_bill_prefill(self, result):
        provenance = dict(result.get("provenance") or {})

        amount = self._coerce_amount(result.get("amount"))
        if result.get("amount") and amount is None:
            provenance.pop("amount", None)

        due_date = self._coerce_date(result.get("due_date"))
        if result.get("due_date") and due_date is None:
            provenance.pop("due_date", None)

        return {
            "vendor_name": result.get("vendor_name"),
            "category": result.get("category"),
            "amount": amount,
            "due_date": due_date,
            "payment_ref": result.get("payment_ref"),
            "provenance": provenance,
        }

    def _coerce_amount(self, value):
        if value in (None, ""):
            return None

        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

        return amount if amount > 0 else None

    def _coerce_date(self, value):
        if not value:
            return None

        try:
            return parse_date(str(value))
        except ValueError:
            return None
