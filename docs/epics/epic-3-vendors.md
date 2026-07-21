# E3 — Vendor Management

**Goal:** user-owned payees with three payment-method types (NETWORK / ACH / CHECK), added via directory search, QR, or manual entry. ⟳ **Bank data is never stored** (BRD §3.4) — raw routing/account go to Moov for tokenization; Swayp keeps only a masked last-4 + provider reference.
**Release:** R1 · **Blocked by:** E1 (S4 mocks, S6 masking/tokenization) · **New app:** `apps/vendors` ([layout](../file-architecture.md#4-planned-new-apps))
**Screens:** 792:13725, 829:4710, 792:16171, 829:4883, 792:16497, 826:2231, 829:14677, 840:14760, 792:16918, 826:2536, 840:15184, 792:17275, 829:9897, 840:15841, 793:1326, 826:2899, 829:10130, 840:16252, 793:1707, 826:3211, 829:10353, 840:16667, 826:1517, 826:1832, 840:14370, 793:2082, 829:3866, 829:4347, 840:26882

> `providers.Provider` stays the **global directory cache**; `Vendor` is the user's payee. Do not merge them.

---

## E3-S1 · Vendor + VendorPaymentMethod models

**As** every vendor feature **I need** the core entities **so that** all three add-paths persist to one shape.

**ORM (`apps/vendors/models/vendor.py`):**
```python
class Vendor(BaseModel):
    user            = FK(settings.AUTH_USER_MODEL, CASCADE, related_name="vendors")
    name            = CharField(max_length=150)
    category        = FK("bill_categories.BillCategory", PROTECT, related_name="vendors")
    logo            = URLField(max_length=500, blank=True)
    business_type   = CharField(max_length=100, blank=True)
    notes           = TextField(blank=True)
    source          = CharField(max_length=20, choices=VendorSource.choices, default=VendorSource.MANUAL)
    status          = CharField(max_length=20, choices=[ACTIVE, DELETED], default=ACTIVE)   # soft delete
    directory_payee_id  = CharField(max_length=100, blank=True)      # network match ref
    directory_verified  = BooleanField(default=False)                # "Verified" badge
    late_fee_amount     = DecimalField(18, 2, null=True, blank=True) # "WeWork charges $160..."
    late_fee_grace_days = PositiveSmallIntegerField(null=True, blank=True)   # "...after 15 days"
    class Meta:
        db_table = "vendors"; ordering = ["name"]
        indexes = [user, status, category, name]
```
**ORM (`apps/vendors/models/vendor_payment_method.py`):**
```python
class VendorPaymentMethod(BaseModel):
    vendor      = FK(Vendor, CASCADE, related_name="payment_methods")
    method_type = CharField(max_length=10, choices=VendorPaymentMethodType.choices)  # NETWORK|ACH|CHECK
    is_primary  = BooleanField(default=False)
    # NETWORK
    network_payee_ref = CharField(max_length=100, blank=True)
    supports_same_day = BooleanField(default=False)
    # ACH — raw routing/account are NEVER stored (BRD §3.4). Sent to Moov → tokenized.
    provider          = CharField(max_length=20, blank=True)         # "MOOV"
    provider_token    = CharField(max_length=100, blank=True)        # Moov payment-method/account token
    account_last4     = CharField(max_length=4, blank=True)          # display only
    account_type      = CharField(max_length=10, choices=BankAccountType.choices, blank=True)
    account_holder_name = CharField(max_length=150, blank=True)
    aba_bank_name     = CharField(max_length=100, blank=True)        # "Chase Bank" from validation
    payee_verified    = BooleanField(default=False)                  # provider-run vendor-account verification (BRD §3.3)
    # CHECK
    check_legal_name = CharField(max_length=150, blank=True)
    street = CharField(max_length=255, blank=True); line2 = CharField(max_length=255, blank=True)
    city = CharField(max_length=100, blank=True); state = CharField(max_length=2, blank=True)
    zip_code = CharField(max_length=10, blank=True)
    check_memo = CharField(max_length=100, blank=True)
    class Meta:
        db_table = "vendor_payment_methods"
        constraints = [UniqueConstraint(fields=["vendor"], condition=Q(is_primary=True), name="one_primary_method_per_vendor")]
```
**AC:**
- [ ] Migrations + admin (masked display) + factory-boy factories
- [ ] Model-level clean(): required fields per `method_type`
- [ ] No routing/account number stored anywhere — DB, logs, backups — plaintext or encrypted (CI grep gate); only `provider_token` + last-4 persist

## E3-S2 · Vendor list, summary & search — `GET vendors/`, `GET vendors/summary/`

**As a** user **I see** my vendors with rail chips and stats (792:13725, 829:4710) **and** can free-text search them in the bill wizard (829:15081).

**API:** `GET vendors/?search=&category=&rail=&status=` (name icontains; rows: name, logo, business_type, rail chip, recurring amount+period, next-due) · `GET vendors/summary/` (total, per-rail counts, check $ total).
**AC:**
- [ ] Paginated + filtered; selector-layer aggregates (no view queries)
- [ ] Summary numbers reconcile with list under the same filters

## E3-S3 · Create vendor (three branches) — `POST vendors/`

**As a** user **I add** a vendor via directory match (826:2536), manual ACH (826:2899), or check mailing details (826:3211), **and get** the "Vendor saved" summary (793:2082).

**API:** single endpoint, `method_type` discriminator; `source` = directory|qr|manual. NETWORK requires `directory_payee_id` (Stripe configured-account ref); ACH requires routing (ABA-validated), account, type, holder — these are **passed to Moov for tokenization and NOT persisted**; CHECK requires legal name + address. Response: masked summary (name, category, method chip, `account_ref: "****8837"`).
**AC:**
- [ ] Three payload branch tests + per-branch required-field validation
- [ ] ACH branch: validates routing (E3-S9), sends routing+account to Moov, stores only `provider_token` + `account_last4` + `aba_bank_name` (raw numbers never hit the DB)
- [ ] Chooser screens (792:16171 etc.) need no endpoint — documented in serializer docstring

> **Tokenization boundary (call clarification, 2026-07-18):** prefer **client-side** tokenization (Moov.js/Drops) so the vendor's raw routing/account **never reach Swayp's backend** — the API receives `{provider_token, last4, bank_name}` only, not merely "receives then doesn't persist." If a server-relay fallback is ever used, raw values pass through memory for a single Moov call and are never written to a model, log, or backup. Same rule applies to re-tokenization in E3-S6.

## E3-S4 · Vendor detail + spend history — `GET vendors/<id>/`

**As a** user **I open** a vendor and see total paid (12 mo), next bill, monthly spend bars, and its bills w/ statuses (829:3866).

**AC:**
- [ ] 12-bucket monthly series from payments (selector annotation, single query)
- [ ] Embedded bills capped (top N by due date) with occurrence-status chips

## E3-S5 · Edit / delete vendor — `PATCH|DELETE vendors/<id>/`

(829:4347, 840:26882) name/category/notes editable; delete = soft (status=DELETED), blocked message if active scheduled payments exist.
**AC:** [ ] soft-delete hides from lists; [ ] history intact; [ ] guard tested

## E3-S6 · Payment-methods sub-resource — `vendors/<id>/payment-methods/`

**As a** user **I change** how a vendor is paid ("Change" links) and may hold ACH *and* CHECK details.

**API:** `GET/POST .../payment-methods/`, `PUT/DELETE .../payment-methods/<mid>/`, `POST .../payment-methods/<mid>/set-primary/`. `GET` accepts `?due_date=&amount=` → per-method computed lead time + initiation date (serves the bill wizard method step, 834:3867/840:11573 — see E4).
**AC:**
- [ ] Masked-field PATCH per E1-S6 (reject `*`, omitted=unchanged). Changing an ACH account **re-tokenizes at Moov** (send full routing+account pair → store new token + last-4); raw numbers never persisted
- [ ] set-primary flips atomically (constraint holds)

## E3-S7 · Directory search — `GET vendors/directory-search/?q=`

**As a** user **I search** the biller directory in real time with Verified/Stripe badges (792:16497, 826:2231, 829:14677, 840:14760).

Behind `VendorDirectoryProvider` (**mock** until PRD §10-Q1 resolves — how Swayp discovers Stripe configured-account vendors; **BILL.com/Melio excluded**, BRD §7); results cached into `providers.Provider`; supersedes `providers/search/` (deprecate in E8-S3 cleanup).
**AC:** [ ] typeahead-fast (mock <50ms), paginated; [ ] result: name, category, network, verified flag; [ ] cache upsert tested

## E3-S8 · QR decode — `POST vendors/qr/decode/`

**As a** user **I scan/upload** a vendor QR and review auto-filled fields with provenance chips (826:1517, 826:1832, 840:14370).

Accepts `{payload}` (decoded string) or multipart image (server-side decode, `pyzbar`/`segno` read). Returns vendor_name, category guess, payment_ref, per-field `provenance: detected|guessed`, optional directory match. Payload spec TBD (PRD §10-Q6) → parser behind a small strategy interface.
**AC:** [ ] both input modes tested; [ ] malformed payload → 422 with clear error

## E3-S9 · ABA routing validation — `POST banking/routing/validate/`

**As a** user typing a routing number **I see** "Valid – Chase Bank (ABA verified)" live (793:1326 et al).

Checksum (mod-10 ABA) + bank-name lookup (local ABA directory table; provider-ready). *Lives in `apps/banking` but shipped in this epic — vendor ACH form depends on it.*
**AC:** [ ] valid/invalid/unknown-bank cases; [ ] rate-limited (public-ish endpoint, auth still required)
