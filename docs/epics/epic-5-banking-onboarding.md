# E5 — Bank Connection & Onboarding

**Goal:** connect a bank read-only (Plaid behind an interface), scan **up to 12 months** of transactions (BRD §3.1), auto-detect recurring bills, and bulk-import them — the 836:* onboarding journey. *(Screens 836:8984/9052 say "24 months" — design bug, PRD §11.)*
**Release:** R2 · **Blocked by:** E1 (S1 Celery, S4 interfaces, S6 crypto), E3, E4 (import creates Vendors + Bills) · **New app:** `apps/banking`
**Screens:** 836:9157, 836:8618, 836:8936, 836:8984, 836:9052, 836:8666, 836:8856

---

## E5-S1 · Banking models

**ORM (`apps/banking/models/bank_connection.py`):**
```python
class BankConnection(BaseModel):
    user             = FK(settings.AUTH_USER_MODEL, CASCADE, related_name="bank_connections")
    provider         = CharField(max_length=20, default="PLAID")
    item_id          = CharField(max_length=100, unique=True)
    access_token     = EncryptedTextField()                      # never serialized
    institution_name = CharField(max_length=100)
    institution_logo = URLField(max_length=500, blank=True)
    status           = CharField(max_length=20, choices=[ACTIVE, DISCONNECTED, ERROR], default=ACTIVE)
    consented_at     = DateTimeField()                           # ESIGN/Plaid disclosure timestamp
    class Meta: db_table = "bank_connections"
```
**ORM (`apps/banking/models/bank_account.py`):**
```python
class BankAccount(BaseModel):
    connection = FK(BankConnection, CASCADE, related_name="accounts")
    name       = CharField(max_length=100)          # "Chase Business"
    mask       = CharField(max_length=4)            # last-4 ("4821")
    account_type = CharField(max_length=10, choices=BankAccountType.choices)
    is_default_funding_source = BooleanField(default=False)
    processor_refs   = JSONField(default=dict, blank=True)   # {"moov_funding_source_id":..} — provider-keyed (Moov/Stripe)
    available_balance = DecimalField(18, 2, null=True); current_balance = DecimalField(18, 2, null=True)
    balance_as_of     = DateTimeField(null=True)
    class Meta: db_table = "bank_accounts"
```
**ORM (`apps/banking/models/transaction_scan.py` + `bill_detection_candidate.py`):**
```python
class TransactionScan(BaseModel):
    connection     = FK(BankConnection, CASCADE, related_name="scans")
    status         = CharField(max_length=10, choices=ScanStatus.choices, default=RUNNING)
    months_history = PositiveSmallIntegerField(default=12)   # BRD §3.1: up to 12 months
    detected_count = PositiveIntegerField(default=0)
    class Meta: db_table = "transaction_scans"

class BillDetectionCandidate(BaseModel):
    scan          = FK(TransactionScan, CASCADE, related_name="candidates")
    vendor_name   = CharField(max_length=150)
    category_guess = FK("bill_categories.BillCategory", SET_NULL, null=True)
    cadence       = CharField(max_length=10, choices=BillFrequency.choices)
    due_day       = PositiveSmallIntegerField()
    amount        = DecimalField(18, 2)
    occurrences   = PositiveSmallIntegerField()          # "3+ occurrences  Confirmed pattern"
    selected      = BooleanField(default=True)
    imported_bill = FK("bills.Bill", SET_NULL, null=True, blank=True)   # idempotency marker
    class Meta: db_table = "bill_detection_candidates"
```
**AC:** [ ] access_token unreadable via API/admin; [ ] factories + migrations

## E5-S2 · Link + exchange — `POST banking/link/token`, `POST banking/link/exchange`

(836:9157, 836:8618, 836:8936, 836:8984) Behind `BankDataProvider` (mock: fake institutions incl. Chase/BofA/WellsFargo/USBank per 836:8618). Exchange stores encrypted token, creates connection + accounts, records `consented_at`, kicks off scan (E5-S4).
**AC:** [ ] mock E2E: token → exchange → connection ACTIVE + accounts w/ masks; [ ] consent timestamp required; [ ] feature-flagged provider selection

> **Customer verification (call clarification, 2026-07-18):** the Plaid connection **is** Swayp's identity/fraud check on its own paying customer — the BRD §4 "lightweight verification at sign-up" = proving the user owns the linked bank account. There is **no separate KYC/IDV vendor or step; do not add one.** (Vendor/payee screening remains the payment provider's job — Moov/Stripe.)

## E5-S3 · Connections + funding accounts — `GET banking/connections`, `DELETE .../<id>/`, `GET banking/accounts`

(836:8856; "Paying from Chase ***4821" on 834:3867/840:27719) Masked accounts + balances + default-funding flag. DELETE revokes at provider + status=DISCONNECTED. *(Settings surface assumed — PRD §10-Q12.)*
**AC:** [ ] only masks exposed; [ ] disconnect blocks if payments in flight (guard tested)

## E5-S4 · Transaction scan + recurring detection — `GET banking/scans/<id>` + Celery

(836:9052 — live progress, "17 recurring bills detected", 4 criteria cards) `sync_transactions` pulls history via provider; `detect_recurring_bills` clusters **deterministically**: same normalized vendor name + amount within tolerance + regular interval + **≥3 occurrences**. No LLM. Writes candidates, updates `detected_count` as it goes (polling endpoint).
**AC:** [ ] fixture transactions → expected candidates (golden tests); [ ] progress observable mid-scan; [ ] thin-history (<180d) degrades gracefully

## E5-S5 · Candidates + bulk import — `GET banking/scans/<id>/candidates`, `POST banking/scans/<id>/import`

(836:8666 "Add All 17 Bills" / "Select Individually") Import `{candidate_ids | all:true}` → per candidate: find-or-create Vendor (source=IMPORT) + Bill (source=DETECTED, anchor from due_day/cadence) + first occurrence. **Idempotent**: candidates with `imported_bill` set are skipped and reported.
**AC:** [ ] re-POST is a no-op with skip report; [ ] created counts returned; [ ] Idempotency-Key honored (E1-S7)

## E5-S6 · Onboarding summary — `GET banking/onboarding-summary`

(836:8856) Connected bank meta, bills detected/imported, total due this month, overdue count, per-vendor rail readiness: network-matched / ACH captured / needs-details counts.
**AC:** [ ] numbers reconcile with E4-S2 summary + E3-S2 stats; [ ] single aggregate query set (selector)
