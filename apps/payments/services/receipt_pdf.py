"""A settled payment's receipt as a PDF (PAY-8).

The same facts as the receipt block on payment detail, laid out for a file
someone forwards to their accountant. Built with reportlab, like the report
exports. Rendered on request rather than stored: the payment row is the
record, and a stored file could drift from it.
"""

import io

from django.http import HttpResponse

from apps.common.dates import EASTERN

RAIL_NAME = {
    "ACH_STANDARD": "ACH (standard)",
    "ACH_SAMEDAY": "ACH (same day)",
    "CHECK": "Mailed check",
    "NETWORK": "Biller network",
}


def _money(value):
    return f"${value:,.2f}"


def _date(value):
    if value is None:
        return "—"

    return f"{value.strftime('%B')} {value.day}, {value.year}"


def render_receipt(payment):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
        title=f"Receipt {payment.transaction_reference}",
    )
    styles = getSampleStyleSheet()

    account = payment.funding_account
    occurrence = payment.bill_occurrence
    paid_on = payment.updated_at.astimezone(EASTERN).date()

    rows = [
        ("Reference", payment.transaction_reference),
        ("Paid to", payment.vendor.name if payment.vendor else "—"),
        ("Paid on", _date(paid_on)),
        ("From", account.masked_name if account else "—"),
        ("Method", RAIL_NAME.get(payment.rail, payment.rail)),
        ("Bill due", _date(occurrence.due_date) if occurrence else "—"),
        ("Expected arrival", _date(payment.estimated_arrival)),
        ("Amount", _money(payment.amount)),
        ("Fee", _money(payment.fee)),
        ("Total", _money(payment.total)),
    ]

    table = Table(rows, colWidths=[1.8 * inch, 4.7 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#CBD5E1")),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#1E3A5F")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    doc.build(
        [
            Paragraph("Swayp payment receipt", styles["Title"]),
            Paragraph(
                f"Payment {payment.transaction_reference} was completed.",
                styles["Normal"],
            ),
            Spacer(1, 18),
            table,
            Spacer(1, 24),
            Paragraph(
                "Swayp arranges this payment; a licensed payment provider "
                "moves the money. Keep this receipt for your records.",
                styles["Italic"],
            ),
        ]
    )

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="swayp-receipt-'
        f'{payment.transaction_reference}.pdf"'
    )

    return response
