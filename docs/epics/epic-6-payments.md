# E6 — Payments & Money Movement

**Goal:** the pay flow end-to-end — batch selection, single authorization, live stages, cancel window, failure recovery, scheduling, auto-pay — fully working against the **mock processor**. Production rails (**Stripe** configured-account, **Moov** ACH, **Lob/PostGrid** checks) are a config swap, gated on the Moov platform application + written legal opinion (PRD §8/R4).
**Release:** R3 · **Blocked by:** E1 (all), E4, E5 · **App:** extend `apps/payments` (migrate to feature packages in the same PR — [policy](../file-architecture.md#3-current-state-per-app-2026-07-16))
**Screens:** 840:27360, 840:27719, 840:28151, 840:28543, 840:28867, 840:13131, 841:29250, 841:29742

> **🔒 Non-custodial invariant (BRD §4, hard):** no code path may let funds rest in a Swayp-controlled balance between debit and credit. Every `Payment` records its executing **licensed provider** (Stripe/Moov/Lob) + provider reference, so any regulator question resolves to a named provider. Money movement is Moov's (ACH) / Stripe's (configured-account); Swayp only orchestrates. Enforced as an architectural invariant, tested.
>
> **Bank transfer only + off-app execution (call clarification, 2026-07-18):** there is **no debit/credit-card rail, ever** — `PaymentRail` is card-free by design. Execution happens **outside Swayp**: Stripe via a hosted payment link + webhook, Moov via tokenized ACH. Swayp orchestrates and consumes webhooks; it never renders a card form or touches PANs.

---

## E6-S1 · Payment model extensions + new entities

**ORM — extend `Payment` (breaking-ish; one migration):**
```python
# make nullable (required today, blocks vendor-only payments):
provider  → FK(..., null=True, blank=True)       # legacy catalog biller
category  → FK(..., null=True, blank=True)
# add:
bill_occurrence  = FK("bills.BillOccurrence", SET_NULL, null=True, related_name="payments")
vendor           = FK("vendors.Vendor", PROTECT, null=True, related_name="payments")
funding_account  = FK("banking.BankAccount", PROTECT, null=True, related_name="payments")
rail             = CharField(choices=PaymentRail.choices)
processor        = CharField(choices=PaymentProcessor.choices, default=MOCK)
batch            = FK("payments.PaymentBatch", SET_NULL, null=True, related_name="payments")
initiated_date   = DateField(null=True); estimated_arrival = DateField(null=True)
cancellation_deadline = DateTimeField(null=True)   # aware, America/New_York
failure_reason   = CharField(max_length=50, blank=True)     # e.g. NSF
failure_detail   = JSONField(default=dict, blank=True)      # {"available_balance": "2180.00", ...}
scheduled_for    = DateField(null=True)             # future-dated send (841:29742)
# transaction_reference REUSED for SWP-YYYYMMDD-NNNN (already unique)
```
**New entities (`apps/payments/models/`):**
```python
class PaymentBatch(BaseModel):                     # one consent covers "Bills (6)" (840:28151)
    user  = FK(AUTH_USER_MODEL, CASCADE, related_name="payment_batches")
    total = DecimalField(18, 2); count = PositiveSmallIntegerField()
    class Meta: db_table = "payment_batches"

class PaymentStage(BaseModel):                     # drives Processing drawer (840:28543); absorbs payment_tracking
    payment = FK(Payment, CASCADE, related_name="stages")
    stage   = CharField(choices=[AUTHORIZED, DEBITING, ROUTING, COMPLETED])
    status  = CharField(choices=PaymentStageStatus.choices, default=PENDING)
    order   = PositiveSmallIntegerField()
    started_at = DateTimeField(null=True); finished_at = DateTimeField(null=True)
    class Meta: db_table = "payment_stages"; constraints = [UniqueConstraint(fields=["payment","stage"], ...)]

class PaymentAuthorization(BaseModel):             # immutable NACHA consent (per payment OR per batch)
    payment = FK(Payment, PROTECT, null=True, blank=True, related_name="authorizations")
    batch   = FK(PaymentBatch, PROTECT, null=True, blank=True, related_name="authorizations")
    authorization_text = TextField()               # verbatim, incl. processor name (sole allowed leak)
    accepted_at = DateTimeField(); ip = GenericIPAddressField(); user_agent = TextField()
    class Meta:
        db_table = "payment_authorizations"
        constraints = [CheckConstraint(exactly one of payment|batch, name="auth_payment_xor_batch")]

class WebhookEvent(BaseModel):                     # dedupe: processors redeliver + reorder
    processor = CharField(max_length=20); event_id = CharField(max_length=100)
    payload = JSONField(); processed_at = DateTimeField(null=True); result = CharField(max_length=50, blank=True)
    class Meta: db_table = "webhook_events"; constraints = [UniqueConstraint(fields=["processor","event_id"], ...)]
```
**AC:** [ ] migrations reversible; [ ] reference generator `SWP-YYYYMMDD-NNNN` (per-day sequence) collision-tested; [ ] authorization rows update-protected

## E6-S2 · Create payments / batch — `POST payments/` (extends existing)

(840:27360, 840:27719) `{occurrence_ids: [...], funding_account_id, rail, scheduled_for?}` → PaymentBatch (when >1) + one Payment per occurrence; marks occurrences SCHEDULED (suppresses reminders); computes initiated/arrival/cancellation deadline via date engine; returns authorization text (from provider interface). Idempotent (E1-S7).
**AC:** [ ] batch + single paths; [ ] `scheduled_for` → status SCHEDULED (no separate schedule endpoint — 841:29742 = same payload); [ ] deadline is aware NY datetime

## E6-S3 · Confirm + consent — `POST payments/batches/<id>/confirm/` (+ single alias)

(840:28151) Records **one** `PaymentAuthorization` for the batch (text verbatim, IP, UA), transitions SCHEDULED/PENDING→PROCESSING, enqueues execution.
**AC:** [ ] consent immutability; [ ] re-confirm replays via idempotency (no second authorization); [ ] processor name appears **only** inside authorization_text (grep gate elsewhere)

## E6-S4 · Status + canonical detail — `GET payments/batches/<id>/status/`, `GET payments/<id>/status/`, `GET payments/<id>/`

(840:28543, 840:28867, deep links from notifications) Poll endpoint: ordered stage checklist + reference. Detail: state-aware (stages; failure block when FAILED; receipt fields when SUCCESSFUL — recipient, amount, funding mask, ETA, reference).
**AC:** [ ] receipt matches 840:28867 fields; [ ] batch status aggregates per-payment stages

## E6-S5 · Cancel window — `POST payments/batches/<id>/cancel/`, `POST payments/<id>/cancel/`

(840:28151 "can be cancelled before 11:59 PM EST today" — stored as NY-aware) Valid from SCHEDULED/PENDING/PROCESSING per amended machine (E1-S3); after deadline → 409.
**AC:** [ ] boundary tests at deadline ±1min incl. DST week; [ ] processor void called via interface when already submitted

## E6-S6 · Failure detail + resolution — `GET payments/<id>/failure/`, `POST payments/<id>/resolve/`

(840:13131, 841:29250, 841:29742) Failure: reason (NSF), available balance at attempt, days overdue, late-fee rule + days remaining (vendor fields, E3-S1). Resolve `{action: retry|change_method|reschedule, payment_method_id?, scheduled_for?}` → **new Payment linked to the same occurrence**.
**AC:** [ ] each action tested; [ ] occurrence keeps single live payment (old one terminal); [ ] late-fee countdown = date-engine math

## E6-S7 · Execution engine + reconciliation (Celery)

`execute_payment`: persist processor idempotency key **before** external call; no blind autoretry on ambiguous errors — on retry, query processor by key first; write "attempt started" stage row. `reconcile_payments` hourly: sweep stuck PROCESSING vs processor state. Mock processor simulates success/NSF-failure/late-return scenarios.
**AC:** [ ] kill-worker-mid-call test → no duplicate debit after recovery; [ ] reconciliation closes a stuck payment in test; [ ] no execution path holds funds in a Swayp balance (non-custodial invariant asserted); [ ] every payment persists its executing provider (Stripe/Moov/Lob) + reference (traceability)

## E6-S8 · Webhooks — `POST webhooks/plaid|<processor>|lob/` (versionless mount)

`WebhookAPIView` base (no auth, per-processor signature verify on raw body, enqueue-and-ack). Consumer: `WebhookEvent` insert-or-skip on unique conflict → transaction + `select_for_update(payment)` → state transition; already-satisfied transitions are no-ops; **late return** → SUCCESSFUL→RETURNED + notification.
**AC:** [ ] duplicate + out-of-order event tests; [ ] bad signature → 400, no event row; [ ] late-return flow updates occurrence back to DUE

## E6-S9 · Autopay + REMIND loop (Celery `autopay_scheduler`)

AUTO bills w/ live `StandingAuthorization`: create payment at `due − lead_time(rail)` referencing standing auth — **no per-payment confirm**. REMIND bills: notification carrying `bill_id`+`occurrence_id`; user approval calls E6-S2 which marks occurrence SCHEDULED → reminders stop.
**AC:** [ ] AUTO without live authorization does nothing (and alerts); [ ] no duplicate payment for an occurrence with one in flight; [ ] NY-timezone beat

## E6-S10 · Deprecations

`PATCH payments/<id>/processing|successful|failed/` → staff-only (transitions are now internal); `payment-tracking/` route removed after `PaymentStage` migration; `providers/search/` superseded by E3-S7.
**AC:** [ ] staff gate tested; [ ] OpenAPI marks deprecated=true before removal

## E6-S11 · Remove the wallet (stored-balance) subsystem

**As** a non-custodial product **we must** delete the internal stored-balance flow **so that** no code path debits/credits a Swayp-held balance (BRD §4; "the wallet is dead" — CEO call 2026-07-18).

> The wallet is **not dormant today** — the legacy `payment_service` actively debits `Wallet.balance` on create and credits it on refund (`apps/payments/services/payment_service.py:100-144, 286-329`). This story runs **only after** E6-S2/S7 re-point payment execution at the Moov/Stripe providers, so removing it doesn't break live endpoints.

**Work (one PR, after the new execution path is green):**
- Strip wallet debit/credit + `WalletTransaction` writes from `payment_service` (funds now move at the provider, never internally).
- Remove `apps.wallet` from `LOCAL_APPS`; drop the `wallet/` include (`api/v1/urls.py`); delete `apps/wallet/`.
- Remove `.select_related("wallet")` in `apps/dashboard/repositories.py`; remove `WalletStatus` (`apps/common/enums.py`) and `WalletFrozenException` / `InsufficientBalanceException` once unreferenced.
- Migration to **delete** `wallets` + `wallet_transactions` tables (note the `WalletTransaction → payments.Payment` OneToOne is dropped with it).

**AC:**
- [ ] No `wallet` import remains outside a migration (grep gate)
- [ ] Payment create/refund pass end-to-end with zero internal balance mutation (non-custodial invariant test from E6-S7 still holds)
- [ ] `wallet/summary/` returns 404/gone; OpenAPI no longer lists it
- [ ] Delete-tables migration is reversible in a test DB
