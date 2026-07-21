# E1 — Platform Foundations

**Goal:** everything later epics assume: task runner, correct currency, expressive payment state machine, pluggable providers, safe date/money math.
**Release:** R1 · **Blocked by:** nothing · **Screens:** none (infrastructure)

---

## E1-S1 · Wire Celery + beat

**As** the platform **I need** a working async task runner **so that** OTP delivery, scans, auto-pay, and webhooks can run off-request.

> Celery/Redis exist only in `requirements.txt` today — no `config/celery.py`, no settings, no `tasks.py` anywhere.

**Work:** `config/celery.py` (app, autodiscover), `config/__init__.py` export, `CELERY_*` settings in `config/settings/base.py` (broker = `REDIS_URL`), beat schedule scaffold **pinned to `America/New_York`**, one health task.
**AC:**
- [ ] `celery -A config worker -B` starts; health task runs
- [ ] Beat timezone = America/New_York (DST-safe)
- [ ] Settings read from env (django-environ), no hardcoded broker

## E1-S2 · Currency default → USD

**As** a US product **I need** USD everywhere **so that** advisor math, checks, and receipts are correct.

**ORM changes (2 migrations):**
```python
# apps/payments/models.py           # apps/wallet/models.py
currency = models.CharField(        currency = models.CharField(
    max_length=10,                      max_length=10,
    choices=Currency.choices,           choices=Currency.choices,
    default=Currency.USD,  # was BDT    default=Currency.USD,  # was BDT
)                                   )
```
**AC:**
- [ ] Both defaults migrated; existing rows data-migrated BDT→USD (confirm with client first — PRD §10-Q4)
- [ ] Serializer/service tests assert USD

## E1-S3 · Enums + payment state machine amendments

**As** later epics **I need** the shared vocabulary and legal transitions **so that** cancel/returns/scheduling are expressible.

**`apps/common/enums.py` — add:**
```python
PaymentRail: ACH_STANDARD, ACH_SAMEDAY, NETWORK, CHECK
PaymentProcessor: MOCK, STRIPE, MOOV, LOB    # STRIPE=configured-account vendors, MOOV=ACH, LOB=checks (BRD §5). Dwolla/GoCardless excluded.
BillFrequency: MONTHLY, QUARTERLY, WEEKLY, ONE_TIME
BillOccurrenceStatus: UPCOMING, DUE, OVERDUE, SCHEDULED, PAID
AutopayMode: AUTO, REMIND
VendorPaymentMethodType: NETWORK, ACH, CHECK
VendorSource: DIRECTORY, QR, MANUAL, IMPORT
BankAccountType: CHECKING, SAVINGS
PaymentStageStatus: PENDING, RUNNING, DONE, FAILED
ScanStatus: RUNNING, DONE, FAILED
PaymentStatus += SCHEDULED, RETURNED
```
⚠️ Do **not** create `OTPPurpose`/`OTPChannel` here — `OTPPurpose` (REGISTRATION/LOGIN/RESET_PASSWORD) already lives in `apps/authentication/models/otp.py`; `OTPChannel` joins it there (E2-S1).

**`apps/payments/state_machine.py` — TRANSITIONS become:**
```python
SCHEDULED  → {PENDING, CANCELLED}
PENDING    → {PROCESSING, CANCELLED}
PROCESSING → {SUCCESSFUL, FAILED, CANCELLED}
SUCCESSFUL → {REFUNDED, RETURNED}      # RETURNED = late ACH return
FAILED / RETURNED / REFUNDED / CANCELLED → {}
```
**AC:**
- [ ] State-machine unit tests cover every legal + illegal transition (today NOTHING can reach CANCELLED)
- [ ] Existing PaymentStateService tests still pass

## E1-S4 · Provider interfaces + mocks (`integrations/`)

**As** every money feature **I need** third parties behind interfaces **so that** the whole product runs with zero external accounts and provider approvals (Moov platform application, legal opinion — PRD §8/R4) don't block work.

**Providers are decided (BRD §5):** `bank_data`=Plaid · `money_movement`=**Stripe** (configured-account vendors) + **Moov** (ACH) · `check_mail`=**Lob/PostGrid** · `directory`=Stripe-configured lookup · `llm`=Anthropic. **Do NOT** wire Dwolla / GoCardless / Stripe-Treasury (excluded on record).
**Work:** top-level `integrations/` package: `bank_data/`, `money_movement/`, `directory/`, `check_mail/`, `llm/` — each `base.py` (ABC) + `mock.py`. Factory reads `FEATURE_*`/`*_PROVIDER` env vars. Mocks are deterministic (fixed balances, instant stage progression, canned directory results).
**AC:**
- [ ] `MoneyMovementProvider.execute(payment) -> ProcessorResult` etc. defined with plain-data DTOs (no Django models across the boundary)
- [ ] Mock money movement emits stage events consumable by E6
- [ ] No processor name reachable from any serializer (grep test) — exception documented for authorization text (E6-S3)

## E1-S5 · Business-day / lead-time engine

**As** payments & bills **I need** correct date math **so that** "arrives Dec 14", "1–3 days", "initiate 2 days early" are true, incl. weekends/holidays/DST.

**Work:** `apps/common/dates.py` (or `integrations/calendar/`): Fed holiday calendar, `add_business_days`, `initiation_date(due, rail)` (ACH = due − 2 biz days per 834:3867), `estimated_arrival(sent, rail)`, month-end clamping (31st → last day; anchor-based recurrence for weekly/quarterly).
**AC:**
- [ ] Table-driven tests: Fri+1=Mon, holiday skip, Feb 29/30/31 clamps, DST boundaries
- [ ] Single module — no other code does date arithmetic on money paths

## E1-S6 · No-raw-storage: masking + provider-tokenization utilities

**As** vendor/bank features **I need** the tools to keep bank data OUT of Swayp **so that** BRD §3.4 holds: raw routing/account numbers are **never stored — not even encrypted**; Swayp keeps only a masked last-4 + a provider reference. "Displayed as …1234 everywhere" (793:1326) is satisfied by the mask, not by decrypting a stored number.

**Work:** `apps/common/crypto.py`:
- `mask_last4()` + serializer helpers (write-only input, **reject values containing `*`**, omitted-on-PATCH = unchanged).
- `EncryptedTextField` (KMS/env key, key-id versioned) — **only for provider secrets/tokens** (e.g. Plaid `access_token`, E5). **Never** for routing/account numbers.
- Tokenization-helper contract: full routing/account go straight to the `MoneyMovementProvider` (Moov) → returns `{provider_token, last4, bank_name}`; Swayp persists only those. Raw numbers never touch a model field, log, or backup.
**AC:**
- [ ] DB dump / logs / backups contain **no** routing/account numbers — plaintext **or** encrypted (CI grep gate)
- [ ] `EncryptedTextField` usage is limited to provider secrets (test asserts no bank-number field uses it)
- [ ] Masked-input-reject + PATCH-unchanged serializer mixin tested

## E1-S7 · IdempotencyKey

**As** money-creating endpoints **I need** idempotency **so that** retries/double-clicks can't double-pay.

**ORM (`apps/payments/models/idempotency_key.py`):**
```python
class IdempotencyKey(BaseModel):
    user         = FK(settings.AUTH_USER_MODEL, CASCADE, related_name="idempotency_keys")
    endpoint     = CharField(max_length=100)
    key          = CharField(max_length=100)          # client Idempotency-Key header
    request_hash = CharField(max_length=64)           # sha256 of body
    state        = CharField(choices=[IN_PROGRESS, COMPLETED], default=IN_PROGRESS)
    response_body = JSONField(null=True, blank=True)
    class Meta:
        db_table = "idempotency_keys"
        constraints = [UniqueConstraint(fields=["user", "endpoint", "key"], name="uniq_idem_user_endpoint_key")]
```
**Behavior:** insert-first (unique constraint wins races) → 409 on same key + different `request_hash` → replay stored response when COMPLETED. Applied via view mixin to: E6 create/confirm/resolve, E5 bulk import.
**AC:**
- [ ] Concurrent duplicate test (two threads, one Payment row)
- [ ] 409 + replay behaviors tested
