# Swayp Backend Plan — Dashboard & Money Movement (Part 2)

**Type:** Implementation plan / prompt file — **no code has been written yet.**
**Source:** All Figma screens listed in [figma_node.md](figma_node.md) (file `b8KwFvXR3UAqb36DYHOP5q`), analyzed screen-by-screen on 2026-07-16. (Note: `836-8666` appears twice in that file — 68 unique screens.)
**Companion doc:** [third-party-services-and-production-requirements.md](third-party-services-and-production-requirements.md) (Part 1 — services, client asks, compliance).
**Verification:** this plan was adversarially reviewed by three independent audit passes (screen coverage vs figma_node.md, repo-consistency vs actual code, API-design) and revised accordingly.

**Repo baseline (verified):** Django 6 + DRF + SimpleJWT + Postgres; drf-spectacular at `/api/docs/`; layered `views → services → selectors → repositories → models`; `BaseAPIView` (auth + `service_class`) used by all apps **except `authentication`** (plain `APIView`, no selectors/repositories); `BaseModel` = UUID pk + timestamps; per-app urls mounted under `api/v1/`. ⚠️ **Celery/Redis are installed as packages but NOT wired** — no `config/celery.py`, no `CELERY_*` settings, no `tasks.py` anywhere; OTP delivery is a `print()` with a TODO. Wiring Celery is Phase 0 work.

---

## 0. How to read this plan

- §1 maps every Figma screen to a feature area.
- §2–3 define the data model, enum/state-machine changes, and cross-cutting conventions.
- §4 is the **complete DRF API surface** (endpoint tables per app) — the core deliverable.
- §5–6 cover services layering and Celery jobs.
- §7 is integration stubbing strategy (rails ARE decided per the BRD — Stripe + Moov + Lob/PostGrid — but still built behind provider interfaces).
- §8 phased delivery; §9 design bugs to report; §10 open questions.

> ⚠️ **BRD reconciliation (2026-07-17):** the CEO BRD ([Swayp BRD Payments.docx.md](Swayp%20BRD%20Payments.docx.md)) resolved the rail/custody/directory/currency questions this doc originally left open. Rails are **Stripe** (configured-account vendors, NETWORK), **Moov** (ACH), **Lob/PostGrid** (checks). **Dwolla / GoCardless / Stripe-Treasury are excluded on record.** Raw bank numbers are **never stored** (tokenized at Moov). **Non-custodial** is mandatory. **USD only.** Billing/Subscriptions (E9) + Teams (E10) are new scope. See [PRD §0](PRD.md).

**Rule for implementers:** every money-movement integration still goes behind a feature flag + provider interface, but the concrete providers are decided (above). The design copy naming Dwolla/Stripe-Treasury/GoCardless (836:9157/8984, 792:16918/834:3867, 840:28151) is now a **design bug** — the originator is Stripe or Moov per rail.

---

## 1. Screen → feature map

| Feature area | Screens (node ids) | Status in repo (verified) |
|---|---|---|
| **Auth & registration** | 1464:15936 (register, Business/Individual), 1464:16992 + 1472:18816 (OTP channel modal ×2 purposes), 1464:17675 + 1473:18911 (OTP entry), 1472:18735 (reset confirm), 1473:18992 (new password), 1464:14947 (login email/user-id + phone-login btn) | **Largely exists**: register (w/ account_type + business fields), verify-otp, resend-otp (w/ purpose), **two-step OTP login** (`login/` sends LOGIN-purpose OTP → `login/verify/` issues tokens), refresh, logout, forgot/reset-password. Gaps: OTP `channel` (email-only this release), resend throttle, phone-identifier login, password history. ✅ Auth api refactored into feature packages (commit `00a6b9a`) — routes verified working. |
| **Bank connect (Plaid) + bill detection onboarding** | 836:9157 (connect intro), 836:8618 (select bank), 836:8936 (bank login mock), 836:8984 (verifying), 836:9052 (scanning transactions), 836:8666 (17 bills found), 836:8856 (bills ready summary) | **Missing** — new `banking` app |
| **Home dashboard** | 565:4649 (Welcome Back, stats, recent bills, vendor list, right-rail pay panel w/ Overdue/Due/Upcoming tabs) | Partial (`dashboard/profile-summary`) — needs home aggregate |
| **Vendors** | 792:13725 + 829:4710 (overview + stats), 792:16171 + 829:4883 (add-method chooser — client-side navigation, no endpoint), 792:16497 + 826:2231 + 829:14677 + 840:14760 (directory search), 792:16918 + 826:2536 + 840:15184 (confirm network vendor), 792:17275 + 829:9897 + 840:15841 (manual: ACH vs check — navigation + data carried into create), 793:1326 + 826:2899 + 829:10130 + 840:16252 (ACH bank details), 793:1707 + 826:3211 + 829:10353 + 840:16667 (check mailing details), 826:1517 (QR scan), 826:1832 + 840:14370 (QR detected/review), 793:2082 (vendor saved), 829:3866 (vendor detail + spend history), 829:4347 + 840:26882 (edit vendor) | **Missing** — new `vendors` app (distinct from global `providers` catalog) |
| **Bills** | 829:13780 (bills overview), 829:14282 (add-bill chooser — navigation), 829:15081 (wizard vendor pick = **saved-vendor search**), 834:3034 + 836:10384 (details step), 834:3436 + 840:10811 (schedule step), 834:3867 + 840:11573 (method step), 834:4324 (review/save), 836:3480 + 840:12320 (bill detail + payment history), 840:13718 (scan bill QR), 840:12632 (invoice modal + QR) | **Missing** — new `bills` app |
| **Pay flow** | 840:27360 (pay a bill, batch select), 840:27719 (payment summary + AI cash context), 840:28151 (confirm & send w/ authorization), 840:28543 (processing stages), 840:28867 (success receipt + next-up), 840:13131 + 841:29250 (payment failed + resolutions), 841:29742 (schedule payment + balance projection) | Partial (`payments` model + state machine) — needs batch, execution, authorization, resolution APIs |
| **Reports** | 666:5374 (vendor + date filter) | **Missing** — new `reports` app (output shape undefined — §10) |
| *(no screens provided)* | Settings surface (bank disconnect, AI consent, notification preferences) — **assumed**, flagged in §10-Q13; webhooks/refresh/logout are screen-less infrastructure | — |

---

## 2. Data model plan

### 2.1 Keep / repurpose (verified against code)

| Existing | Decision |
|---|---|
| `providers.Provider` + `GET providers/` + `GET providers/search/` | **Keep as the global biller/directory catalog.** `providers/search/` functionally overlaps the new V8 directory-search — fold it in or deprecate (§4.10). Do NOT overload Provider as the user's vendor. |
| `payments.Payment` + `PaymentStateMachine` | Keep, extend (fields + transitions below). ⚠️ `Payment.provider` and `Payment.category` are **required FKs (PROTECT)** today — must become nullable (or migrate to vendor FK) or payments to manual/QR/check vendors cannot exist. |
| `payments.Payment.transaction_reference` | **Reuse** for the `SWP-YYYYMMDD-NNNN` reference format (already unique). No second reference column. |
| `payment_tracking.PaymentTracking` | Absorb into `PaymentStage` (per-payment ordered stages, screen 840:28543). Deprecate route after migration. |
| `wallet.Wallet` (+ live `GET wallet/summary/`) | Not in any screen. Keep dormant; **include `Wallet.currency` BDT→USD default in the Phase 0 currency sweep** (it also defaults to BDT). |
| `bill_categories.BillCategory` | Keep — feeds Category dropdowns (Telecom, Commercial Rent, Utilities, SaaS…). |
| `users.User/Profile/BusinessProfile/IndividualProfile` | Keep — matches the Business/Individual registration split. ⚠️ Login screen says "Email or User ID" but `User` has `USERNAME_FIELD="email"` and **no user-id/handle column** — needs a decision (§10-Q12). |
| `authentication.OTP` | **Already has** `purpose` (REGISTRATION/LOGIN/RESET_PASSWORD), `expires_at`, `attempts`, and purpose-scoped verification in serializers/services. Genuinely missing: `channel` (SMS/EMAIL) + a resend throttle + real delivery (currently `print()`). |

### 2.2 New / changed models

**`authentication`** (extend — smaller than originally scoped)
- `OTP`: add `channel` (`SMS | EMAIL`) + resend-throttle metadata. Purpose, expiry, attempts, and purpose isolation **already exist** — do not rebuild.
- `PasswordHistory` (user FK, password hash, created_at) — enforce "must differ from previous password" (1473:18992).

**`banking` (new app)**
- `BankConnection` — user FK, provider (`PLAID`), `item_id`, `access_token` (**encrypted**), institution name/logo, status (`ACTIVE|DISCONNECTED|ERROR`), consent timestamps.
- `BankAccount` — connection FK, masked last-4, account type, `is_default_funding_source`, processor references (nullable, provider-interface keyed), available/current balance snapshot + `balance_as_of`.
- `TransactionScan` — connection FK, status (`RUNNING|DONE|FAILED`), months_history, detected_count (836:9052 progress).
- `BillDetectionCandidate` — scan FK, vendor_name, category guess, cadence, due_day, amount, occurrences, selected flag, `imported_bill_id` (nullable — makes bulk import **idempotent**: already-imported candidates are skipped and reported).

**`vendors` (new app)** — user-owned payees
- `Vendor` — user FK, name, category FK, logo URL, notes, business type, status (`ACTIVE|DELETED`), `source` (`DIRECTORY | QR | MANUAL | IMPORT`), directory refs (network payee id, verified flag), late-fee policy (`late_fee_amount`, `late_fee_grace_days` — 840:13131/841:29250: "WeWork charges $160 after 15 days").
- `VendorPaymentMethod` — vendor FK, `method_type` (`NETWORK | ACH | CHECK`), `is_primary`, discriminated payloads:
  - NETWORK: network payee ref, auto-managed routing, speed capability.
  - ACH: routing + account **sent to Moov for tokenization and NOT persisted** (BRD §3.4); store only `provider_token` + masked `account_last4`, account_type (`CHECKING|SAVINGS`), account_holder_name, ABA-validation result (`aba_bank_name`), `payee_verified` (provider-run vendor-account verification, BRD §3.3).
  - CHECK: legal_name, street, line2, city, state, zip, default check memo.
  - Modeled one-to-many (a vendor may hold ACH *and* CHECK details) — hence the sub-collection API in §4.3.

**`bills` (new app)**
- `Bill` — user FK, vendor FK, `bill_type` (`FIXED|VARIABLE`), amount, category FK, notes, frequency (`MONTHLY|QUARTERLY|WEEKLY|ONE_TIME`), **`anchor_date`** (first due date; subsequent dates derived from frequency with explicit **month-end clamping** — 31st → last day of month; weekly uses anchor's weekday; quarterly anchors to anchor month), `autopay_mode` (`AUTO|REMIND`), preferred `payment_method` FK, source (`MANUAL|QR|DETECTED`).
  - ⚠️ Do **not** store a mutable `Bill.status` — status is **computed at read time in selectors** from occurrences (a recurring bill is never globally "PAID").
- `BillOccurrence` — **mandatory, not optional**: bill FK, due_date, amount (for VARIABLE), status (`UPCOMING|DUE|OVERDUE|SCHEDULED|PAID`), payment FK (nullable). Every list/tab/stat in the UI (Overdue 14 / Due 9 / Upcoming 14, "Paid 3", payment history) is an **occurrence-level** query; resolves the 565:4649 count mismatch (§10-Q11).
- `StandingAuthorization` — bill FK, authorization text, accepted_at, ip, user_agent, revoked_at. **Created when the user sets `autopay_mode=AUTO`** (L3/L5 require an explicit consent field). NACHA recurring debits need a standing authorization captured from the user — a Celery job cannot mint consent (it has no user, IP, or user-agent). Revoking autopay revokes it.

**`payments` (extend `Payment`)**
- `bill_occurrence` FK (nullable), `vendor` FK, make `provider`/`category` **nullable**, `funding_account` FK, `rail` (`ACH_STANDARD | ACH_SAMEDAY | NETWORK | CHECK`), `processor` (`MOCK | STRIPE | MOOV | LOB` — NETWORK→STRIPE, ACH_*→MOOV, CHECK→LOB), `batch` FK (nullable), `initiated_date`, `estimated_arrival`, `cancellation_deadline` (**aware datetime computed in America/New_York** — never a fixed EST offset), `failure_reason` + `failure_detail` (JSON), `scheduled_for` (nullable — a "scheduled payment" is just a Payment with `scheduled_for` + status SCHEDULED; no separate schedule endpoint).
- `PaymentBatch` — user FK, total, count. One **batch-level confirm/status/cancel** — screen 840:28151 shows ONE authorization for "Bills (6)", not N confirmations.
- `PaymentStage` — payment FK, ordered stages (`AUTHORIZED → DEBITING → ROUTING → COMPLETED/FAILED`) with per-stage status/timestamps (840:28543). Absorbs `payment_tracking`.
- `PaymentAuthorization` — payment-or-batch FK, authorization text shown, accepted_at, ip, user agent (**immutable NACHA consent record**).
- `WebhookEvent` — processor, `event_id` (**unique together**), payload, received_at, processed_at, result. Webhook consumers insert-or-skip on conflict, process in a transaction with `select_for_update` on the Payment, and treat already-satisfied transitions as no-ops — processors redeliver and deliver out of order.
- `IdempotencyKey` — unique (user, endpoint, key), request-body hash, state (`IN_PROGRESS|COMPLETED`), stored response. Insert-first wins races; same key + different body → 409; COMPLETED replays the stored response. Covers P1, P2, P8, B8, and batch endpoints.
- Currency: **default `BDT` → `USD`** (also `Wallet.currency` — §2.1).

**`ai_advisor` (new app)** — `AdvisorConsent` (user FK, consented_at, revoked_at); math in Python, LLM phrases only (Part 1 §3.5).

**`reports` (new app)** — query-time aggregation; `ReportExport` later if downloads required (§10-Q5).

**`notifications`** (extend) — add types BILL_DUE, PAYMENT_FAILED, PAYMENT_REVERSED, AUTOPAY_EXECUTED, PAYMENT_ARRIVED, LATE_FEE_WARNING; `NotificationPreference` (user FK, type, channel toggles). ⟳ **email + in-app only this release (BRD §1.2)** — SMS/push columns reserved, no adapters. Reminder notifications carry `bill_id` + `occurrence_id` so approval deep-links into P1 (§6 REMIND loop).

**`billing` (new app — E9, from BRD §6.2)** — `Plan` (code, price, seat/bank/check limits, included_entities, price_locked), `Subscription` (account, plan, period, locked_price), `AllowanceCounter` (per subscription/kind/cycle: checks/seats/banks), `FeeCharge` (same-day-ACH $4.99 / expedited-check $8.99 / check-overage $2.99 ledger; state PENDING|BILLED|REFUNDED), `EnterpriseAddOn` (extra-entity $79 / workflow $99 / ERP $149 / SLA $199). Same-day-ACH fee is not created after the bank cutoff; missed delivery guarantees auto-refund. Full stories in [epics/epic-9-billing.md](epics/epic-9-billing.md).

**`teams` (new app — E10)** — `TeamMember` (account, user, email, role, status; seat-limited per plan), `Entity` (Enterprise multi-entity; `Vendor`/`Bill`/`Payment` gain a nullable `entity` FK once enabled). Full stories in [epics/epic-10-teams.md](epics/epic-10-teams.md).

### 2.3 Enum & state-machine changes (`apps/common/enums.py`, `apps/payments/state_machine.py`)

New enums:
```
PaymentRail: ACH_STANDARD, ACH_SAMEDAY, NETWORK, CHECK
PaymentProcessor: MOCK, STRIPE, MOOV, LOB     # STRIPE=configured-account (NETWORK), MOOV=ACH, LOB=checks (BRD §5)
BillFrequency: MONTHLY, QUARTERLY, WEEKLY, ONE_TIME
BillOccurrenceStatus: UPCOMING, DUE, OVERDUE, SCHEDULED, PAID
AutopayMode: AUTO, REMIND
VendorPaymentMethodType: NETWORK, ACH, CHECK
VendorSource: DIRECTORY, QR, MANUAL, IMPORT
BankAccountType: CHECKING, SAVINGS
OTPChannel: SMS, EMAIL          # lives in authentication app beside the existing OTPPurpose
PaymentStageStatus: PENDING, RUNNING, DONE, FAILED
ScanStatus: RUNNING, DONE, FAILED
```

⚠️ **Do NOT create a new OTPPurpose.** It already exists at `apps/authentication/models/otp.py` with `REGISTRATION | LOGIN | RESET_PASSWORD` and live flows depend on all three (including the stored value `"RESET_PASSWORD"`). If relocated to common, keep all members and values (or plan a data migration).

`PaymentStatus`: add `SCHEDULED` and `RETURNED`. **Amend `PaymentStateMachine.TRANSITIONS` explicitly** (today there is *no inbound transition to CANCELLED at all*, so P4 cancel would be rejected):
```
SCHEDULED  → PENDING, CANCELLED
PENDING    → PROCESSING, CANCELLED
PROCESSING → SUCCESSFUL, FAILED, CANCELLED   # cancel inside the 11:59 PM ET window
SUCCESSFUL → REFUNDED, RETURNED              # late ACH returns arrive days after success
FAILED/RETURNED/REFUNDED/CANCELLED → terminal
```

---

## 3. Cross-cutting conventions

1. **No raw storage + masking (BRD §3.4):** raw routing/account numbers are **never persisted** (not even encrypted) — they go straight to Moov for tokenization; Swayp keeps only `provider_token` + masked last-4. Reads return `"****4821"`. **Update semantics:** masked values rejected as input (reject anything containing `*`); on PATCH, omitted sensitive fields mean *unchanged*; changing an account re-tokenizes at Moov (full routing+account pair → new token). Field-level encryption (KMS via env) is used **only for provider secrets/tokens** (e.g. Plaid `access_token`), never bank numbers.
2. **Money:** `DecimalField(max_digits=18, decimal_places=2)`; all amounts USD.
3. **Timezones:** all money deadlines are aware datetimes in **America/New_York** (DST-correct — never "EST"). Celery beat crontabs pinned to America/New_York. Day-boundary for due dates = ET (product decision to confirm, §10).
4. **Pagination/filtering:** `apps/common/pagination.py` on **every** list endpoint (incl. V8 directory search, R1 reports, L7 history); `django-filter` for status/category/vendor/date-range. V4's embedded bills are capped (top N + link to `L1 ?vendor=`).
5. **Responses/errors:** reuse `apps/common/responses.py` + `exception_handler.py`.
6. **Views:** endpoints are `BaseAPIView` subclasses with `service_class` (align `authentication` to this convention during Phase 2, or explicitly exempt it). **Exception — webhooks:** a separate `WebhookAPIView` base with `authentication_classes=[]`, per-processor signature verification on the raw body, enqueue-to-Celery-and-ack pattern, 400 on bad signature.
7. **Idempotency:** via the `IdempotencyKey` model (§2.2) — not middleware. Enumerated endpoints: P1 (create/batch), P2 (confirm), P8 (resolve), B8 (bulk import).
8. **Lead-time engine:** one utility computes `initiation_date = due_date − rail_lead_time` (ACH initiates 2 days early per 834:3867) and `estimated_arrival`, using a **Fed business-day calendar** (Part 1 §3.9). Never naive date math. Month-end clamping rules live here too (§2.2 Bill).
9. **OpenAPI:** drf-spectacular annotations on all new endpoints.
10. **Processor naming:** structured fields expose only `rail`, never `processor` — **except** the server-generated legal authorization text (NACHA consent must identify the originator/processor). That string is produced by the provider interface (changes with the feature flag) and stored verbatim in `PaymentAuthorization`.

---

## 4. API surface (DRF)

All paths under `api/v1/`, following existing conventions. New app prefixes: `banking/`, `vendors/`, `bills/`, `ai/`, `reports/`, `webhooks/`.

### 4.1 `auth/` (extend existing — inventory verified against code)

> ✅ **Auth api refactor complete (commit `00a6b9a`):** `serializers/`, `views/`, `urls/` are now per-feature packages with re-exporting `__init__.py`s; the `serailizers` typo is fixed; all 9 routes reverse + generate OpenAPI. No repair needed.

| # | Method & path | Status | Plan | Screens |
|---|---|---|---|---|
| A1 | `POST auth/register/` | **exists** (account_type, business_name, poc_name, billing_address, conditional BUSINESS validation) | Verify against final Figma schema only; "Bill Corresponding Data" mapping is the open item (§10-Q4 — may already be `billing_address`) | 1464:15936 |
| A2 | `POST auth/otp/send/` | partial (`resend-otp/` exists and already accepts `purpose`) | Add `channel` (⟳ **email-only this release, BRD §1.2**; SMS reserved) + resend throttle + real delivery (Celery task replaces the `print()`) | 1464:16992, 1472:18816 |
| A3 | `POST auth/verify-otp/` | **exists** (purpose-scoped) | Keep; optionally rename to `otp/verify/` (document as a rename, not new) | 1464:17675, 1473:18911 |
| A4 | `POST auth/resend-otp/` | **exists** | Add throttle | same |
| A5 | `POST auth/login/` → `POST auth/login/verify/` | **exists as a two-step OTP flow** (login validates credentials + sends LOGIN-purpose OTP; login/verify issues tokens) | Extend identifier to email **or user-id** — ⚠️ no user-id column exists on `User` (§10-Q12) | 1464:14947 |
| A6 | `POST auth/login/phone/request/` + `POST auth/login/phone/verify/` | new **pair** | Reuse the existing LOGIN-purpose OTP machinery with a phone identifier — two endpoints, not one | 1464:14947 |
| A7 | `POST auth/forgot-password/` | **exists** | Identifier carries from login screen (1472:18735 has no input — §9-8) | 1472:18735 |
| A8 | `POST auth/reset-password/` | **exists** | Add password-history rule (`PasswordHistory`) | 1473:18992 |
| A9 | `POST auth/refresh/`, `POST auth/logout/` | exist | unchanged (screen-less infrastructure) | — |

### 4.2 `banking/` (new)

| # | Method & path | Purpose | Screens |
|---|---|---|---|
| B1 | `POST banking/link/token/` | Create Plaid link_token (flagged; MOCK provider in dev) | 836:9157, 836:8618, 836:8936 |
| B2 | `POST banking/link/exchange/` | Exchange public_token → encrypted item; create connection + accounts; kick off scan | 836:8984 |
| B3 | `GET banking/connections/` | Connections + masked accounts + status | 836:8856 *(+ assumed settings surface — §10-Q13)* |
| B4 | `DELETE banking/connections/<uuid:connection_id>/` | Disconnect / revoke | *assumed settings — no screen provided (§10-Q13)* |
| B5 | `GET banking/accounts/` | Funding sources w/ masked last-4 + balances ("Paying from Chase ***4821") | 834:3867, 840:27719 |
| B6 | `GET banking/scans/<uuid:scan_id>/` | Scan progress: status, detected_count ("17 recurring bills detected") | 836:9052 |
| B7 | `GET banking/scans/<uuid:scan_id>/candidates/` | Detected-bill candidates | 836:8666 |
| B8 | `POST banking/scans/<uuid:scan_id>/import/` | `{candidate_ids: [...] \| all: true}` → bulk-create Vendors + Bills. **Idempotent** — already-imported candidates skipped and reported | 836:8666 |
| B9 | `GET banking/onboarding-summary/` | Connected bank meta, bills detected/imported, total due, overdue count, per-vendor rail readiness | 836:8856 |
| B10 | `POST banking/routing/validate/` | ABA checksum + bank-name lookup → `{valid, bank_name}` | 793:1326, 826:2899, 829:10130, 840:16252 |

### 4.3 `vendors/` (new)

| # | Method & path | Purpose | Screens |
|---|---|---|---|
| V1 | `GET vendors/?search=&category=&rail=&status=` | List w/ **free-text search** (name) — also serves the Save-Bill wizard's saved-vendor picker. Rows: name, logo, business type, rail chip, recurring amount + period, next-due | 792:13725, 829:4710, 565:4649, **829:15081** |
| V2 | `GET vendors/summary/` | Stat cards: total, per-rail counts (Stripe 9 / ACH 4), check total $ | 792:13725, 829:4710 |
| V3 | `POST vendors/` | Create — `method_type` discriminator (NETWORK / ACH / CHECK), `source` (directory\|qr\|manual). Returns masked summary for "Vendor saved". *(Chooser screens 792:16171, 829:4883, 792:17275, 829:9897 are client-side navigation into this endpoint — no dedicated API.)* | 826:2536, **792:16918**, 840:15184, 826:2899, 829:10130, 840:16252, 826:3211, **793:1707**, **829:10353**, 840:16667, 793:2082, 840:15841 |
| V4 | `GET vendors/<uuid:vendor_id>/` | Detail: header + method chip, total paid (12mo), next bill, monthly spend series, nested bills (capped, occurrence-status) | 829:3866 |
| V5 | `PATCH vendors/<uuid:vendor_id>/` | Edit name, category, notes | 829:4347, 840:26882 |
| V6 | `DELETE vendors/<uuid:vendor_id>/` | Soft-delete | 829:4347 |
| V7 | `GET/POST vendors/<uuid:vendor_id>/payment-methods/`; `PUT/DELETE vendors/<uuid:vendor_id>/payment-methods/<uuid:method_id>/`; `POST .../<uuid:method_id>/set-primary/` | **Sub-collection, not a singleton** — matches the one-to-many `VendorPaymentMethod` model and the "Change" links. GET also powers the wizard method step (see L8 rehoming): pass `?due_date=&amount=` to get computed lead times + initiation dates per method | 829:4347, 840:26882, 834:3867, 840:11573 |
| V8 | `GET vendors/directory-search/?q=` | Typeahead proxy of the biller directory (⚠️ backing service unresolved — mock behind interface; cache into `providers.Provider`; supersedes `providers/search/`). Paginated | 792:16497, 826:2231, 829:14677, 840:14760 |
| V9 | `POST vendors/qr/decode/` | `{payload}` or multipart image → vendor_name, category guess, payment_ref, per-field provenance + optional directory match | 826:1517, 826:1832, 840:13718, 840:14370 |

### 4.4 `bills/` (new — all statuses are **occurrence-level**)

| # | Method & path | Purpose | Screens |
|---|---|---|---|
| L1 | `GET bills/?status=&vendor=&date_from=&date_to=` | Occurrence-backed list: vendor+logo, due date, status chip, amount | 829:13780, 840:27360, 565:4649 |
| L2 | `GET bills/summary/` | Total due this month, per-status counts (tabs: Overdue/Due/Upcoming; cards: overdue, scheduled, paid) | 829:13780, 565:4649 |
| L3 | `POST bills/` | Create from wizard: vendor_id, bill_type, amount, category, notes, frequency, **anchor_date**, autopay_mode (+ **explicit consent field when AUTO → creates `StandingAuthorization`**), payment_method_id; seeds first `BillOccurrence`; returns review echo | 829:15081, 834:3034, **834:3436**, 834:3867, 834:4324, 829:14282 |
| L4 | `GET bills/<uuid:bill_id>/` | Meta + aggregates (overdue amt + days, next due, autopay, total paid) | 836:3480, 840:12320 |
| L5 | `PATCH bills/<uuid:bill_id>/` | Edit details / schedule / method (AUTO toggle re-captures standing authorization) | 836:10384, 840:10811, 840:11573, 834:3436 |
| L6 | `DELETE bills/<uuid:bill_id>/` | Remove bill (kebab menu) | 829:13780 |
| L7 | `GET bills/<uuid:bill_id>/payments/` | Paginated payment history | 836:3480, 840:12320 |
| L8 | *(rehomed)* | Method step during **creation** has no bill yet → use `GET vendors/<id>/payment-methods/?due_date=&amount=` (V7). For the **edit** flow, `GET bills/<id>/payment-methods/` may alias it | 834:3867, 840:11573 |
| L9 | `POST bills/qr/decode/` | Bill-QR parse: vendor + amount + due date (+ directory match); shares impl with V9 | 829:14282, 840:13718 |
| L10 | `GET bills/<uuid:bill_id>/invoice/` | Invoice render data (from bill fields — ingestion/OCR out of scope, §10-Q8) | 840:12632 |
| L11 | `GET bills/next-due/` | Nearest upcoming occurrence ("Next up: Verizon $389 due Dec 15") — bill concern, so it lives here (not under payments) | 840:28867, 840:27719 |

### 4.5 `payments/` (extend existing app)

| # | Method & path | Purpose | Screens |
|---|---|---|---|
| P1 | `POST payments/` | exists — **extend**: `{occurrence_ids: [...], funding_account_id, rail, scheduled_for?}`. Multiple occurrences → creates a **`PaymentBatch`** + one Payment per occurrence; `scheduled_for` → status SCHEDULED (no separate schedule endpoint). Marks occurrences SCHEDULED (suppresses reminders). Returns per-payment initiated/arrival/cancellation-deadline + authorization text | 840:27360, 840:27719, 841:29742 |
| P2 | `POST payments/batches/<uuid:batch_id>/confirm/` (single-payment convenience: `POST payments/<uuid:payment_id>/confirm/`) | Records **one** `PaymentAuthorization` covering the batch (screen shows one consent for "Bills (6)"), transitions SCHEDULED/PENDING→PROCESSING, enqueues execution | 840:28151 |
| P3 | `GET payments/batches/<uuid:batch_id>/status/` + `GET payments/<uuid:payment_id>/status/` | Stage checklist (authorized/debiting/routing) + reference — polled by Processing drawer | 840:28543 |
| P4 | `POST payments/batches/<uuid:batch_id>/cancel/` + `POST payments/<uuid:payment_id>/cancel/` | Cancel before `cancellation_deadline` (America/New_York-aware). Requires the §2.3 transition additions | 840:28151 |
| P5 | `GET payments/<uuid:payment_id>/` | **Canonical payment detail** (state-aware: embeds stages; failure block when FAILED; receipt fields when SUCCESSFUL). Notification deep-links land here. P3 stays as the lightweight poll | 840:28867, 840:13131 |
| P7 | `GET payments/<uuid:payment_id>/failure/` | Failure detail: reason (NSF), available balance at attempt, days overdue, late-fee rule + days remaining (thin projection of P5) | 840:13131, 841:29250 |
| P8 | `POST payments/<uuid:payment_id>/resolve/` | `{action: retry \| change_method \| reschedule, payment_method_id?, scheduled_for?}` — creates the follow-up payment linked to the same occurrence | 840:13131, 841:29250, 841:29742 |
| P10 | `GET payments/history/` | exists — keep; extend filters (vendor, bill, status, date-range) | 836:3480 |
| P11 | existing `PATCH processing/ successful/ failed/` | **Deprecate for client use** — transitions become internal (webhook/task-driven); keep behind staff permission for admin/testing | — |

### 4.6 `dashboard/` (extend)

| # | Method & path | Purpose | Screens |
|---|---|---|---|
| D1 | `GET dashboard/home/` | Greeting, stat cards (due this month $, total bills, paid), recent bills, vendors preview (rail chips, $/mo), right-rail occurrence tab counts + top overdue | 565:4649 |
| D2 | `GET dashboard/profile-summary/` | exists — keep | — |

### 4.7 `ai/` (new)

| # | Method & path | Purpose | Screens |
|---|---|---|---|
| AI1 | `POST ai/cash-context/` | NL sentence + structured figures (balance now/after, upcoming bills, next bill). Math in Python; LLM phrases only; consent-gated; killswitch flag; template fallback | 840:27719, 840:28151 |
| AI2 | `GET ai/balance-projection/?account=<id>&date=<d>` | Projected balance on date X ("$44,100 on Dec 18") | 841:29742 |
| AI3 | `POST/DELETE ai/consent/` | Record/revoke advisor consent (GLBA opt-in) | *assumed settings — no screen provided (§10-Q13)* |

### 4.8 `reports/` (new)

| # | Method & path | Purpose | Screens |
|---|---|---|---|
| R1 | `GET reports/?vendor=<id>&date_from=&date_to=` | Filtered payment/bill rows, paginated (columns/export TBD — §10-Q5) | 666:5374 |

### 4.9 `webhooks/` (new — `WebhookAPIView` base per §3.6, all feature-flagged)

| # | Method & path | Purpose |
|---|---|---|
| W1 | `POST webhooks/plaid/` | JWT-verified; `SYNC_UPDATES_AVAILABLE` → enqueue sync |
| W2 | `POST webhooks/<processor>/` | Signature-verified transfer events → `WebhookEvent` insert-or-skip → transactional stage/state transitions (handles **late ACH returns** via SUCCESSFUL→RETURNED) |
| W3 | `POST webhooks/lob/` | Check lifecycle (mailed / in-transit / returned-to-sender → FAILED) |

### 4.10 Existing endpoints — disposition
`bill-categories/` keep (feeds dropdowns) · `notifications/` keep + add types & `GET/PATCH notifications/preferences/` (channel toggles per type) · `providers/` keep as directory cache; **`providers/search/` fold into V8 or deprecate** · `wallet/summary/` keep dormant (include in currency sweep) · `payment-tracking/` deprecate after `PaymentStage` migration · auth two-step login endpoints keep as-is (§4.1).

---

## 5. Services / layering

Each new app mirrors `payments`: thin `views.py` (`service_class`), `services/`, `selectors/`, `repositories.py`, `serializers.py`, `schemas.py`, `urls.py`.

- `banking.PlaidService` → `BankDataProvider` interface (`MockBankDataProvider` for dev/tests).
- `banking.RecurringDetectionService` — deterministic clustering (same vendor + similar amount + regular interval + ≥3 occurrences — the four criteria on 836:9052). No LLM.
- `vendors.DirectoryService` → `VendorDirectoryProvider` interface (**mock**; how Swayp discovers Stripe configured-account vendors is PRD §10-Q1 — **Melio/BILL.com excluded**, BRD §7).
- `vendors.QRService` — payload parse + per-field provenance.
- `payments.PaymentExecutionService` → `MoneyMovementProvider` interface (`MockProcessor` default; **Stripe** (configured-account) + **Moov** (ACH) stubs; **Lob/PostGrid** for checks). **Non-custodial** — funds never rest in a Swayp balance; each payment records its executing provider. Rail selection, lead-time calc, reference generation (`SWP-YYYYMMDD-NNNN` reusing `transaction_reference`, per-day DB sequence), cancellation windows.
- `payments.ResolutionService` — retry / change-method / reschedule (validated against the amended state machine).
- `bills.ScheduleService` — occurrence generation from `anchor_date` + frequency with month-end clamping; **single source of truth** for business-day/lead-time math (§3.8).
- `ai.CashContextService` — Python math + provider-neutral LLM wrapper (template fallback).

## 6. Celery jobs (⚠️ Celery must first be wired — Phase 0)

All beat crontabs pinned to **America/New_York** (§3.3).

| Job | Trigger | Does |
|---|---|---|
| `send_otp` | on A2 | Deliver OTP via channel (replaces the `print()` TODO) |
| `sync_transactions` | Plaid webhook / nightly | `/transactions/sync`, balance refresh |
| `detect_recurring_bills` | after sync / after B2 | Write `BillDetectionCandidate`s; update scan progress |
| `generate_occurrences` | daily beat | Roll forward `BillOccurrence`s from anchor_date + frequency |
| `autopay_scheduler` | daily beat | AUTO bills w/ live `StandingAuthorization`: create payment at `due − lead_time` referencing the standing auth (**no per-payment confirm**). REMIND bills: send notification carrying `bill_id` + `occurrence_id`; user approval calls P1, which marks the occurrence SCHEDULED and suppresses further reminders |
| `execute_payment` | on P2 / autopay | **Double-debit protection:** persist a per-payment processor idempotency key BEFORE the external call; no blind auto-retry on ambiguous errors — on retry, first query the processor by that key to reconcile; write an "attempt started" stage row so crashed attempts are detectable |
| `reconcile_payments` | hourly beat | Sweep stuck PROCESSING / crashed-attempt payments against processor state |
| webhook consumer | W1–W3 | `WebhookEvent` dedupe → transactional transitions (out-of-order tolerant) |
| `bill_status_notifier` | daily beat | Late-fee countdowns + due-reminders (status itself is computed at read time, not by this job) |

## 7. Integration stubbing strategy (critical)

1. Provider interfaces: `BankDataProvider`, `MoneyMovementProvider`, `VendorDirectoryProvider`, `CheckMailProvider`, `LLMProvider`.
2. `Mock*` implementations first — the entire §4 surface works end-to-end against mocks.
3. Real processors (Stripe/Moov/Lob) wired at R4/Phase 7 — gated on the Moov platform application + written legal opinion (PRD §8); each behind `FEATURE_*` flags.
4. Processor names never leak through structured fields — sole exception: the legal authorization text (§3.10).

## 8. Phased delivery

| Phase | Scope | Depends on |
|---|---|---|
| **0. Foundations** | **Wire Celery (app + beat + broker settings) — currently packages-only**; enums + state-machine amendments (§2.3); Currency defaults → USD (**Payment AND Wallet**, two migrations); provider interfaces + mocks; business-day/lead-time engine; masking/encryption utils; `IdempotencyKey` | none |
| **1. Vendors + Bills CRUD** | `vendors` + `bills` apps (V1–V9, L1–L11 vs occurrence model), D1 aggregate; QR decode (payload only) | 0 |
| **2. Auth gaps** | A2 email delivery + resend throttle, A6 phone pair, A8 password history; align auth to `BaseAPIView` convention (feature-package refactor already done, commit `00a6b9a`) | 0 (parallel w/ 1) |
| **3. Banking + onboarding** | `banking` app B1–B10 vs mock provider; scan → candidates → idempotent bulk import; onboarding summary | 1 |
| **4. Payments execution** | P1–P11 incl. **batches**, stages, authorization + standing-authorization records, resolution, `WebhookEvent` consumers, autopay + reconciliation jobs | 1 |
| **5. AI advisor** | AI1–AI3 template-first → LLM behind flag + consent | 3 |
| **5b. Billing + Teams** | `billing` app (plans, allowance counters, per-txn fees, delivery-guarantee refunds, Enterprise add-ons) + `teams` app (seats, invitations, entities) vs mock billing; enforce seat/bank/check limits (E9/E10) | 1, 4 |
| **6. Reports + polish** | R1 (+1099, plan-gated), notification types + preferences (email/in-app), deprecations (`payment-tracking`, P11 PATCHes, `providers/search/`) | 1–4 |
| **7. Real rails** | Swap mocks for **Stripe + Moov + Lob/PostGrid + Plaid + Anthropic** (BRD §5) + production credentials | ⟳ **Moov platform application (2–4 wks) + written legal opinion (Texas + operating states, 1–2 wks)** — hard gates (BRD §4/§6.1) |

Phases 0–2 are buildable **today** with zero external accounts.

## 9. Design bugs to report to the design team

1. `829:4347` / `840:26882` — button label **"Discord"** → "Discard".
2. `793:1707` / `826:3211` / `829:10353` / `840:16667` — **State field placeholder = "Suite, unit, etc."** (copy-paste from Address Line 2).
3. `840:16667` — check-mailing drawer's primary button says **"Save ACH Vendor"**.
4. `834:4324` — "withoutany"; `836:3480`/`840:12320` — "11 daus pverdie".
5. `836:8856` — "**$33,7771**" malformed amount.
6. `840:28867` — receipt mixes WeWork headline with "Recipient: AT&T Business"; "Account: $3,200" label/value mismatch.
7. `1464:15936` — sign-up footer says "Don't have an account? **Create Account**" (should be "Already have an account? Sign In").
8. `1472:18735` — Reset Password screen has **no identifier input**.
9. `840:28151` — authorization copy names **GoCardless**; other screens imply Dwolla/Stripe-Treasury. All superseded — the copy must name the actual originator (**Stripe** or **Moov** per rail, BRD §5).

## 10. Open questions (🔴 = blocking)

1. ✅ **RESOLVED (BRD §5):** rails are **Stripe** (configured-account/NETWORK) + **Moov** (ACH) + **Lob/PostGrid** (checks). Dwolla/GoCardless/Treasury excluded. *Residual:* how Swayp **discovers** Stripe configured-account vendors (V8) — Melio/BILL.com excluded (BRD §7).
2. ✅ **RESOLVED:** "Stripe Bill Pay Network" isn't a real product; the model is Stripe configured-account vendors. Discovery mechanism folded into #1.
3. ✅ **RESOLVED (BRD §4):** **non-custodial** is mandatory — Moov (licensed) moves money, funds never rest in a Swayp balance. Gate: **written legal opinion** before the Moov path goes to production (R4/Phase 7).
4. `1464:15936` — what is **"Bill Corresponding Data"**? (May already be the implemented `billing_address`.)
5. `666:5374` — Reports output: table? CSV/PDF export? Columns?
6. Late-fee intelligence — user-entered per vendor (plan assumes) or inferred?
7. QR payload spec (vendor/bill/invoice QRs) — V9/L9 assume JSON/URL payload.
8. Invoice modal (`840:12632`) — render from bill fields (assumed) or stored invoice docs (needs OCR/storage — Part 1 §3.6)?
9. Payee (vendor account) verification before first ACH credit (Part 1 §3.8) — micro-deposits in MVP?
10. Batch semantics — plan: one `Payment` per occurrence + `PaymentBatch` with batch-level confirm/status/cancel. Confirm total-display logic ("Bills (6)" but "$3,200" shown).
11. `565:4649` tab counts (14/9/14) vs "Total Bills 6" — resolved by **occurrences** (counts = occurrences, totals = bills); confirm with design.
12. **Login "Email or User ID"** — `User` has no user-id/handle column (`USERNAME_FIELD=email`). Add a username field, or treat "User ID" as email-only copy?
13. **Settings screens missing** — bank disconnect (B4), AI consent (AI3), notification preferences all assume a settings surface no screen defines. Request designs.
14. Due-date day-boundary timezone: ET (plan assumes) or per-user timezone?

---

*Next step: client answers §10 (esp. Q1/Q2); Phase 0–2 tickets can be cut directly from §2–§4. Phases 0–6 run entirely against mock providers — no external accounts needed until Phase 7.*
