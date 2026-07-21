# E4 — Bill Management & Occurrences

**Goal:** bills as recurring rules with **occurrences** (the unit every screen actually shows), the 5-step wizard, auto-pay consent, and accurate schedules.
**Release:** R1 · **Blocked by:** E3 (vendors), E1-S5 (date engine) · **New app:** `apps/bills`
**Screens:** 829:13780, 829:14282, 829:15081, 834:3034, 836:10384, 834:3436, 840:10811, 834:3867, 840:11573, 834:4324, 836:3480, 840:12320, 840:13718, 840:12632, 565:4649

> **Design decision (from adversarial review):** `BillOccurrence` is **mandatory**. A monthly bill is never globally "PAID"; the tabs "Overdue 14 / Due 9 / Upcoming 14" vs "Total Bills 6" (565:4649) only reconcile if counts are occurrences and totals are bills. `Bill` has **no stored status** — status is computed per occurrence at read time.

---

## E4-S1 · Bill, BillOccurrence, StandingAuthorization models

**ORM (`apps/bills/models/bill.py`):**
```python
class Bill(BaseModel):
    user           = FK(settings.AUTH_USER_MODEL, CASCADE, related_name="bills")
    vendor         = FK("vendors.Vendor", PROTECT, related_name="bills")
    bill_type      = CharField(max_length=10, choices=[FIXED, VARIABLE], default=FIXED)
    amount         = DecimalField(18, 2)                       # per-cycle default; VARIABLE overrides per occurrence
    category       = FK("bill_categories.BillCategory", PROTECT, related_name="bills")
    notes          = TextField(blank=True)
    frequency      = CharField(max_length=10, choices=BillFrequency.choices)
    anchor_date    = DateField()      # first due date; recurrence derives from it (NOT due_day_of_month —
                                      # weekly needs weekday, quarterly needs anchor month, 29-31 needs clamping)
    autopay_mode   = CharField(max_length=10, choices=AutopayMode.choices, default=AutopayMode.REMIND)
    payment_method = FK("vendors.VendorPaymentMethod", SET_NULL, null=True, related_name="bills")
    source         = CharField(max_length=10, choices=[MANUAL, QR, DETECTED], default=MANUAL)
    class Meta: db_table = "bills"; indexes = [user, vendor, category]
```
**ORM (`apps/bills/models/bill_occurrence.py`):**
```python
class BillOccurrence(BaseModel):
    bill     = FK(Bill, CASCADE, related_name="occurrences")
    due_date = DateField()
    amount   = DecimalField(18, 2)
    status   = CharField(max_length=10, choices=BillOccurrenceStatus.choices, default=UPCOMING)
    # payments reference the occurrence: payments.Payment.bill_occurrence FK (E6-S1); retries = new Payment, same occurrence
    class Meta:
        db_table = "bill_occurrences"
        constraints = [UniqueConstraint(fields=["bill", "due_date"], name="uniq_occurrence_per_due_date")]
        indexes = [bill, due_date, status]
```
**ORM (`apps/bills/models/standing_authorization.py`):** *(NACHA: a beat job cannot mint consent — capture it when the user enables AUTO)*
```python
class StandingAuthorization(BaseModel):
    bill               = FK(Bill, CASCADE, related_name="standing_authorizations")
    authorization_text = TextField()          # exact text shown at consent time
    accepted_at        = DateTimeField()
    ip                 = GenericIPAddressField()
    user_agent         = TextField()
    revoked_at         = DateTimeField(null=True, blank=True)   # revoked when autopay turned off
    class Meta: db_table = "standing_authorizations"; ordering = ["-accepted_at"]
```
**AC:** [ ] migrations + factories; [ ] UPCOMING→DUE→OVERDUE derivable purely from `due_date` + linked payment state (documented property)

## E4-S2 · Bills list + summary — `GET bills/`, `GET bills/summary/`

(829:13780, 840:27360, 565:4649) Occurrence-backed rows: vendor+logo, due date, status chip, amount; filters `status|vendor|date_from|date_to`. Summary: total due this month, per-status counts.
**AC:** [ ] status computed in selector annotations (no beat-job staleness — a bill due today reads DUE immediately); [ ] counts = occurrences (reconciles 565:4649); [ ] paginated

## E4-S3 · Create bill (wizard) — `POST bills/`

(829:15081 → 834:4324) Payload: vendor_id, bill_type, amount, category, notes, frequency, anchor_date, autopay_mode, payment_method_id, **`autopay_consent` (bool + shown text) required when AUTO** → creates `StandingAuthorization`. Seeds first occurrence(s). Response echoes the review summary ("Swayp will pay WeWork $3,200 on Jan 1…").
**AC:** [ ] AUTO without consent → 400; [ ] REMIND creates no authorization; [ ] wizard method step served by `GET vendors/<id>/payment-methods/?due_date=&amount=` (E3-S6 — no bill_id needed pre-create)

## E4-S4 · Bill detail + payment history — `GET bills/<id>/`, `GET bills/<id>/payments/`

(836:3480, 840:12320) Aggregates: overdue amount + days-overdue, next due, autopay state, total paid; paginated payment history (date, status, payment-status, amount).
**AC:** [ ] "11 days overdue" computed via date engine; [ ] history joins Payment via occurrence

## E4-S5 · Edit / delete bill — `PATCH|DELETE bills/<id>/`

(836:10384, 840:10811, 840:11573) Any wizard section editable; toggling AUTO re-captures standing authorization; turning off revokes it. Delete cascades future (unpaid) occurrences only.
**AC:** [ ] consent re-capture/revoke tested; [ ] paid history preserved on delete

## E4-S6 · Occurrence engine (Celery `generate_occurrences`)

Daily beat (America/New_York): roll occurrences forward from `anchor_date` + `frequency` with month-end clamping (31st→last day, weekly=anchor weekday, quarterly=anchor month cadence); horizon = next 2 cycles.
**AC:** [ ] idempotent (unique constraint absorbs re-runs); [ ] table-driven recurrence tests incl. Feb/DST

## E4-S7 · Bill QR + invoice — `POST bills/qr/decode/`, `GET bills/<id>/invoice/`

(829:14282, 840:13718, 840:12632) QR returns vendor + amount + due date + optional directory match (shares parser with E3-S8). Invoice modal renders from bill fields (no OCR in v1 — PRD §10-Q8); includes payment ref for the invoice QR.
**AC:** [ ] shared parser, one code path; [ ] invoice payload matches modal fields (840:12632)

## E4-S8 · Next-due — `GET bills/next-due/`

(840:28867 "Next up: Verizon $389 due Dec 15", 840:27719) Nearest upcoming occurrence w/ vendor, amount, due date. Bill-domain endpoint (not payments).
**AC:** [ ] excludes occurrences already SCHEDULED/paid; [ ] empty state defined
