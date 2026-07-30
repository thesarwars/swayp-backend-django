"""CSV and PDF export for the reports (E8-S2, PRD §10-Q4 resolved: both).

Two rules shape everything here.

**An export is the whole filtered set, not the page you were looking at.**
Pagination is a screen concern; someone exporting for their accountant wants
every row the filters matched. So the export path re-runs the query with the
page size raised to a hard cap rather than reusing the paginated result.

**The cap is real and is disclosed.** An unbounded export is a way to take the
process down with one request, so it stops at ``MAX_EXPORT_ROWS`` and says so
in the file itself. A truncated export that looks complete is worse than one
that admits it.
"""

import csv
import io
from decimal import Decimal

from django.http import HttpResponse

#: Enough for a year of heavy use, small enough to render and stream without
#: holding an unbounded result set in memory.
MAX_EXPORT_ROWS = 10_000

CSV = "csv"
PDF = "pdf"
SUPPORTED_FORMATS = (CSV, PDF)

#: Keys are paths into a *serialized* row, so the export shows exactly what
#: the on-screen table shows. Serializing rather than reading the model keeps
#: one definition of a row — notably the Eastern date, which a raw created_at
#: would file under the wrong day for five hours every evening.
PAYMENT_COLUMNS = [
    ("date", "Date"),
    ("vendor.name", "Vendor"),
    ("bill.due_date", "Bill due"),
    ("amount", "Amount"),
    ("fee", "Fee"),
    ("total", "Total"),
    ("currency", "Currency"),
    ("rail", "Rail"),
    ("status", "Status"),
    ("reference", "Reference"),
]

FORM_1099_COLUMNS = [
    ("vendor_name", "Vendor"),
    ("count", "Payments"),
    ("amount", "Amount"),
    ("fee", "Fee"),
    ("total", "Total"),
]


def _cell(value):
    """Render one value for a file rather than for JSON.

    ``None`` becomes an empty cell, not the string "None" — a spreadsheet
    column full of "None" is worse than a blank one, and a blank is what every
    tool that reads these expects.
    """
    if value is None:
        return ""

    if isinstance(value, Decimal):
        return f"{value:.2f}"

    return str(value)


def _get(row, path):
    """Read a possibly-nested key out of a serialized row.

    ``vendor.name`` rather than ``vendor`` — the row serializer nests vendor
    and bill, and a spreadsheet column wants the label, not the object.
    """
    value = row

    for part in path.split("."):
        if not isinstance(value, dict):
            return None

        value = value.get(part)

        if value is None:
            return None

    return value


def _rows_for(columns, rows):
    return [[_cell(_get(row, key)) for key, _ in columns] for row in rows]


# --- CSV -------------------------------------------------------------------


def to_csv(*, filename, columns, rows, totals_row=None, notes=()):
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    for note in notes:
        # A leading comment row rather than a separate sidecar: the caveat has
        # to travel with the file, because the file is what gets emailed on.
        writer.writerow([f"# {note}"])

    writer.writerow([label for _, label in columns])
    writer.writerows(_rows_for(columns, rows))

    if totals_row:
        writer.writerow([])
        writer.writerow(totals_row)

    response = HttpResponse(
        buffer.getvalue(),
        content_type="text/csv; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'

    return response


# --- PDF -------------------------------------------------------------------


def to_pdf(*, filename, title, subtitle, columns, rows, totals_row=None,
           notes=()):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
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
    # Landscape: nine columns of payment data will not read on portrait, and a
    # report nobody can read is not an export.
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title=title,
    )

    styles = getSampleStyleSheet()
    story = [
        Paragraph(title, styles["Title"]),
        Paragraph(subtitle, styles["Normal"]),
        Spacer(1, 12),
    ]

    for note in notes:
        story.append(Paragraph(note, styles["Italic"]))

    if notes:
        story.append(Spacer(1, 8))

    data = [[label for _, label in columns]] + _rows_for(columns, rows)

    if totals_row:
        data.append(totals_row)

    if len(data) == 1:
        story.append(Paragraph("No rows matched these filters.",
                               styles["Normal"]))
    else:
        table = Table(data, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F8FAFC")]),
        ]

        if totals_row:
            style += [
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
            ]

        table.setStyle(TableStyle(style))
        story.append(table)

    doc.build(story)

    response = HttpResponse(
        buffer.getvalue(), content_type="application/pdf"
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'

    return response


# --- report-specific assembly ---------------------------------------------


def _truncation_note(row_count):
    if row_count < MAX_EXPORT_ROWS:
        return ()

    return (
        f"Truncated at {MAX_EXPORT_ROWS:,} rows. Narrow the date range to "
        "export the rest.",
    )


def payments_export(*, fmt, result, filters):
    from apps.reports.api.serializers.report import ReportRowSerializer

    rows = ReportRowSerializer(result["rows"], many=True).data
    totals = result["totals"]

    parts = ["All payments"]

    if filters.get("date_from") or filters.get("date_to"):
        parts.append(
            f"{filters.get('date_from') or 'start'} to "
            f"{filters.get('date_to') or 'today'}"
        )

    if filters.get("vendor_name"):
        parts.append(filters["vendor_name"])

    subtitle = " · ".join(parts)

    totals_row = [
        "TOTAL", "", "",
        _cell(totals.get("amount")),
        _cell(totals.get("fee")),
        _cell(totals.get("total")),
        "", "", f"{totals.get('count', 0)} payments", "",
    ]

    notes = _truncation_note(len(rows))

    if fmt == CSV:
        return to_csv(
            filename="swayp-payments",
            columns=PAYMENT_COLUMNS,
            rows=rows,
            totals_row=totals_row,
            notes=notes,
        )

    return to_pdf(
        filename="swayp-payments",
        title="Payments report",
        subtitle=subtitle,
        columns=PAYMENT_COLUMNS,
        rows=rows,
        totals_row=totals_row,
        notes=notes,
    )


def form_1099_export(*, fmt, result):
    rows = result["rows"]
    totals = result["totals"]
    unattributed = result.get("unattributed") or {}

    notes = list(_truncation_note(len(rows)))

    # Money that could not be tied to a vendor is disclosed on the file, not
    # only in the JSON. A tax export that silently omits spend is the one
    # failure mode here that actually costs the customer something.
    if unattributed.get("count"):
        notes.append(
            f"Excludes {unattributed['count']} payment(s) totalling "
            f"{_cell(unattributed.get('total'))} that are not attributed to "
            "a vendor."
        )

    notes.append(
        "Data view for tax preparation. Not an IRS form, and no reporting "
        "threshold has been applied."
    )

    totals_row = [
        "TOTAL",
        _cell(totals.get("count")),
        _cell(totals.get("amount")),
        _cell(totals.get("fee")),
        _cell(totals.get("total")),
    ]

    year = result.get("year")

    if fmt == CSV:
        return to_csv(
            filename=f"swayp-1099-{year}",
            columns=FORM_1099_COLUMNS,
            rows=rows,
            totals_row=totals_row,
            notes=notes,
        )

    return to_pdf(
        filename=f"swayp-1099-{year}",
        title=f"1099 vendor totals — {year}",
        subtitle="Successful payments by vendor",
        columns=FORM_1099_COLUMNS,
        rows=rows,
        totals_row=totals_row,
        notes=notes,
    )
