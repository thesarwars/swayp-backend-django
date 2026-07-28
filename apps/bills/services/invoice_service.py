"""Bill invoice payload (E4-S7).

Rendered from bill fields only — no OCR in v1 (PRD §10-Q8). Includes the
payment reference the invoice QR encodes, so the modal and the QR agree.
"""

from apps.bills.selectors.occurrence_status import annotate_status


class InvoiceService:

    def build(self, bill, occurrence=None):
        """Invoice fields for ``bill``, defaulting to its next open occurrence."""
        if occurrence is None:
            occurrence = (
                annotate_status(bill.occurrences.all())
                .order_by("due_date")
                .first()
            )

        vendor = bill.vendor
        method = bill.payment_method

        return {
            "bill_id": bill.id,
            "occurrence_id": occurrence.id if occurrence else None,
            "vendor_name": vendor.name,
            "vendor_logo": vendor.logo,
            "category": bill.category.name,
            "bill_type": bill.bill_type,
            "frequency": bill.frequency,
            "amount": occurrence.amount if occurrence else bill.amount,
            "due_date": occurrence.due_date if occurrence else None,
            "status": (
                getattr(occurrence, "computed_status", occurrence.status)
                if occurrence
                else None
            ),
            "autopay_mode": bill.autopay_mode,
            "payment_method": method.method_type if method else None,
            "notes": bill.notes,
            "payment_reference": self.payment_reference(bill, occurrence),
            "qr_payload": self.qr_payload(bill, occurrence),
        }

    def payment_reference(self, bill, occurrence):
        """Stable reference for the invoice and its QR.

        Prefers a reference a real payment already recorded; otherwise derives
        a deterministic one from the bill and due date.
        """
        if occurrence and occurrence.payment_reference:
            return occurrence.payment_reference

        if occurrence:
            return f"SWAYP-{str(bill.id)[:8].upper()}-{occurrence.due_date:%Y%m%d}"

        return f"SWAYP-{str(bill.id)[:8].upper()}"

    def qr_payload(self, bill, occurrence):
        """The string the invoice QR encodes.

        Deliberately the same ``k=v;k=v`` shape the shared parser reads, so a
        Swayp invoice can be scanned straight back into the wizard.
        """
        parts = [
            f"vendor={bill.vendor.name}",
            f"ref={self.payment_reference(bill, occurrence)}",
        ]

        if occurrence:
            parts.append(f"amount={occurrence.amount}")
            parts.append(f"due={occurrence.due_date:%Y-%m-%d}")

        return "SWAYP:" + ";".join(parts)
