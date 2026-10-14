"""Bill QR decode (E4-S7).

Delegates to the vendor QR parser. The acceptance criterion is explicitly
"shared parser, one code path" — this module adds bill-shaped interpretation
on top of a single decode implementation, it does not re-parse anything.
"""

from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_date

from apps.bill_categories.models import BillCategory
from apps.common.enums import VendorStatus
from apps.vendors.models import Vendor
from apps.vendors.services.qr_decoder import QRDecodeService


class BillQRService:

    def __init__(self):
        self.decoder = QRDecodeService()

    def decode(self, *, user=None, payload=None, image=None):
        """Decode a QR into bill-wizard prefill fields.

        Raises ValueError for unreadable input, which the view maps to 422.
        """
        if payload:
            result = self.decoder.decode_payload(payload)
        else:
            result = self.decoder.decode_image(image)

        prefill = self._as_bill_prefill(result)
        prefill.update(self._match_ids(user, prefill))

        return prefill

    def _match_ids(self, user, prefill):
        """The account's own vendor and the category the QR names (BILLS-2).

        The wizard needs ids, and the QR only carries names. Matched exactly
        (case aside) and never invented: a name that matches nothing is
        null, and the client falls back to the search box. A matched
        vendor's own category stands in when the QR names none.
        """
        vendor = None

        if user is not None and prefill.get("vendor_name"):
            vendor = Vendor.objects.filter(
                user=user,
                status=VendorStatus.ACTIVE,
                name__iexact=prefill["vendor_name"].strip(),
            ).first()

        category_id = None

        if prefill.get("category"):
            category_id = (
                BillCategory.objects.filter(
                    is_active=True, name__iexact=prefill["category"].strip()
                )
                .values_list("id", flat=True)
                .first()
            )

        if category_id is None and vendor is not None:
            category_id = vendor.category_id

        from apps.vendors.services.directory_match import directory_match

        method = vendor.primary_payment_method if vendor else None

        return {
            "vendor_id": vendor.id if vendor else None,
            "category_id": category_id,
            # As vendors/qr/decode answers (web C9): the matched vendor's
            # primary method type, and a biller-directory entry by name.
            "payment_method": method.method_type if method else None,
            "directory_match": directory_match(prefill.get("vendor_name")),
        }

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
