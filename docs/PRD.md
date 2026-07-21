# Swayp Backend — Product Requirements Document (PRD)

| | |
|---|---|
| **Product** | Swayp — US business bill-pay platform (backend/API) |
| **Version** | 2.0 — reconciled with the CEO Business Requirements Document (BRD v1.1) |
| **Date** | 2026-07-17 |
| **Status** | BRD resolved the prior blocking questions; remaining clarifications in §10 |
| **Authority** | **[Swayp BRD Payments.docx.md](Swayp%20BRD%20Payments.docx.md) (CEO, authoritative for business logic) → Figma FDD screens ([figma_node.md](figma_node.md)) → [dashboard-plan.md](dashboard-plan.md) / [Part 1](third-party-services-and-production-requirements.md) (engineering planning; partially superseded — see §0.1).** Where the BRD and a screen disagree, the BRD wins and the screen is flagged as a design bug. |
| **Backlog** | [epics/](epics/README.md) |

---

## 0. What changed in v2.0 (BRD reconciliation)

The CEO BRD is now the source of truth for the payments architecture. It **resolves** all four prior blockers and **overrides** several earlier engineering assumptions.

### 0.1 Superseded assumptions (do not build against these)
| Earlier doc said | BRD says (authoritative) |
|---|---|
| ACH processor undecided (Dwolla / GoCardless / Stripe Treasury) | **Two-tier: Stripe** (configured-account vendors) + **Moov** (bank routing/account vendors). Dwolla, GoCardless, Stripe Treasury are **not** used. |
| Consider Melio / BILL.com for a vendor directory | **Rejected on record** (§7) — any AP/AR/bill-pay competitor is excluded. |
| Store routing/account numbers **encrypted at rest** in Swayp | **Never store raw bank data at all** (not even encrypted) — tokenize at the provider; keep only masked value + provider reference (§3.4). |
| Swayp performs payee OFAC/SDN + fraud screening | **Provider's responsibility, not Swayp's** (§4). Swayp does only lightweight verification of its own paying customers at sign-up. |
| Custody question open | **Non-custodial is a hard requirement**; Moov (licensed) moves the money; written legal opinion required before production (§4). |

### 0.2 New scope the BRD introduces
- **Billing & Subscriptions subsystem** (plans, per-plan allowances, overages, same-day/expedited fees, **auto-refunds on missed delivery guarantees**, Enterprise add-on line items) — new **[E9]**.
- **Teams & multi-entity** (team-member limits per plan; Enterprise multi-entity, approval workflows, ERP sync) — new **[E10]**.
- Advisor is named **Flo**; **1099 reporting** is a Standard-plan feature.

---

## 1. Overview

Swayp lets a US business (or individual) **see and pay all of its bills from one place — without Swayp ever holding, storing, or transmitting customer funds.** A user connects their business bank account once (read-only, via **Plaid**); Swayp reads balance and up to 12 months of history to detect recurring bills; and the user pays vendors by one of three rails:

- **Stripe** — vendors that already have a configured payment account with our processor (fast "confirm, send, done").
- **Moov** — vendors identified only by a bank **routing + account number** (ACH); standard 1–3 business days (free) or same-day (+$4.99, pre-cutoff only).
- **Lob / PostGrid** — printed & mailed **physical checks**; standard 5–7 business days (per-plan free allowance) or expedited 1–2 business days (+$8.99).

Payments are recurring-aware (auto-pay with standing authorization, or remind-me), failure-recoverable (incl. late ACH reversals), and fronted by **Flo**, an AI cash-context advisor that projects balances before every payment. The product is **USD-only** and **non-custodial** by legal design.

This PRD covers the **backend API**. The frontend is designed (Figma FDD) and out of scope here.

## 2. Problem statement

Small businesses juggle bills across utility portals, emailed invoices, and paper checks. They miss due dates (late fees), lack cash-flow visibility at the moment of payment, and re-enter vendor bank details repeatedly. Swayp centralizes vendors, bills, scheduling, and payment execution — while staying non-custodial so it never becomes a licensed money transmitter, and never storing raw banking data.

## 3. Goals & non-goals

### Goals
1. Register (Business/Individual), verify via OTP (email), and log in (two-step OTP).
2. Connect a bank **once** (Plaid, read-only); that single connection also serves as **proof of ownership** when money later moves from that account — the customer is never asked to re-verify their own bank (BRD §3.1).
3. Auto-detect recurring bills from up to 12 months of history and import them.
4. Add a vendor either as a **Stripe configured-account** vendor or a **Moov bank-number** vendor (one-time vendor-account verification), or as a **check** vendor (mailing address). Raw bank numbers are **never stored** — masked value + provider reference only.
5. Create bills (fixed/variable; monthly/quarterly/weekly/one-time) with auto-pay (standing authorization) or remind-me.
6. Pay one or many bills: Stripe one-click; Moov standard (free) or same-day (+$4.99, pre-cutoff); check standard (allowance) or expedited (+$8.99). Single authorization per batch; live stages; cancel window; failure/reversal recovery.
7. Accurate send/arrival dates (Fed business-day + cutoff aware). Flo cash context (consent-gated; whether explicit opt-in is legally required is pending legal review — §10.11).
8. **Billing**: track per-plan allowances, bill overages correctly, auto-refund same-day/expedited fees on missed delivery guarantees, and itemize Enterprise add-ons.
9. Reports (incl. 1099 reporting on Standard+).

### Non-goals (this release)
- **SMS notifications** — email only (BRD §1.2). *(Conflicts with the SMS-OTP screen — see §10.)*
- **Invoice OCR / auto-import** — deferred pending a separate CEO decision (BRD §6).
- **BILL.com / Melio / any AP-AR / bill-pay competitor** as infrastructure (BRD §7).
- **Holding funds** in a Swayp-controlled balance, even briefly (BRD §4.1).
- **Any non-USD currency** (BRD §3.5).
- Card payments, payroll, customer-facing invoicing, international payments.
- Choosing rails: **already chosen** (Stripe + Moov + Lob/PostGrid). v1 still builds against **mock providers** behind interfaces so work isn't gated on provider approvals.

## 4. Users / personas

| Persona | Account type | Needs |
|---|---|---|
| **Finance admin / owner** ("Maria") | BUSINESS | Pay vendors on time, batch payments, cash-flow safety, audit trail, manage team members |
| **Individual** ("Jhon") | INDIVIDUAL | Personal recurring bills, reminders, simple pay-now |
| **Team member** | — | Invited to a business account within the plan's seat limit |
| **Enterprise multi-entity admin** | BUSINESS (Enterprise) | Multiple entities, approval workflows, ERP sync (later phase) |

## 5. Functional requirements

IDs map to epics (`E#`) in [epics/](epics/README.md); screen ids are Figma nodes. **New/changed by the BRD is marked ⟳.**

### FR-1 Authentication & accounts (E2)
- FR-1.1 Register BUSINESS (business name, POC, billing address) or INDIVIDUAL (1464:15936). *(exists)*
- FR-1.2 ⟳ OTP verification **via email** (purposes REGISTRATION / LOGIN / RESET_PASSWORD; resend throttle). SMS OTP deferred with SMS notifications (BRD §1.2) — screen shows SMS (1464:16992); see §10.
- FR-1.3 Two-step login (credentials → OTP → tokens) *(exists)*; phone-number login pair (1464:14947).
- FR-1.4 Password reset with OTP; new password must differ from previous (1473:18992).
- FR-1.5 ⟳ **Lightweight customer verification** at sign-up only (BRD §4) — Swayp does **not** verify vendors or run sanctions/fraud screening.

### FR-2 Bank connectivity (E5) — Plaid
- FR-2.1 Connect a business bank read-only during sign-up; Swayp never sees/stores banking credentials (836:9157–8936, BRD §3.1).
- FR-2.2 Read **real-time balance** (powers Flo cash context) (BRD §3.1).
- FR-2.3 ⟳ Scan **up to 12 months** of transaction history to auto-detect recurring bills (BRD §3.1). *(Screens 836:8984/9052 say "24 months" — design bug, §11.)* Recurring detection is a Plaid capability (BRD §5), with deterministic clustering as the implementation baseline.
- FR-2.4 ⟳ **One connection, two purposes**: the sign-up bank link is also instant proof of ownership when Swayp later moves money from that account — never re-verify the customer's own bank (BRD §3.1). (Plaid → Moov processor handoff.)
- FR-2.5 Onboarding: candidate review + bulk import + summary (836:8666, 836:8856).
- FR-2.6 Real-time ABA routing validation with bank-name resolution (793:1326) — validate, then hand to provider; do not store raw.

### FR-3 Vendor management (E3) — two-tier
- FR-3.1 Vendor list + free-text search + per-rail stats (792:13725, 829:4710, 829:15081).
- FR-3.2 ⟳ Add a **Stripe configured-account vendor**: vendor already set up with our processor; no bank details collected; payment is one-click later (BRD §3.2; 792:16918, 826:2536, 840:15184).
- FR-3.3 ⟳ Add a **Moov bank-number vendor**: collect vendor routing + account **once**; **verify the vendor's account is real & correct before the first payment** (typo protection, BRD §3.3); thereafter pay like any vendor (793:1326, 826:2899).
- FR-3.4 Add a **check vendor**: mailing address only (793:1707, 826:3211).
- FR-3.5 ⟳ **Data handling (BRD §3.4, hard):** raw routing/account numbers are ever received only on the **Moov** path (the Stripe configured-account path collects no bank details, FR-3.2). Any raw number entered is transmitted to Moov for tokenization and stored **on Moov's systems**, **never** in Swayp's DB, logs, or backups — not even encrypted. Swayp retains only a **masked display value** (e.g. ••••4821) and a **provider reference id**.
- FR-3.6 Vendor detail (12-mo spend, total paid, next bill, bills) (829:3866); edit/delete; manage payment method (829:4347).
- FR-3.7 Vendor late-fee policy fields drive "no late fee yet — N days left" (840:13131).

### FR-4 Bill management (E4)
- FR-4.1 Bills are recurring rules with **occurrences**; all statuses/tabs/counts are occurrence-level (829:13780, 565:4649).
- FR-4.2 5-step create wizard: vendor → details → schedule → method → review (829:15081 → 834:4324).
- FR-4.3 Auto-pay ON requires an explicit consent step recording a **standing authorization** (NACHA); remind-me mode notifies instead (834:3436).
- FR-4.4 Bill detail: overdue amount/days, next due, auto-pay, total paid, payment history (836:3480).
- FR-4.5 Bill QR decode (vendor + amount + due date); invoice modal from bill fields (840:13718, 840:12632).

### FR-5 Payments & money movement (E6) — non-custodial
- FR-5.1 ⟳ **Stripe path** (configured-account vendor): one confirmed action → success/failure known automatically via webhook; no sensitive data stored by Swayp (BRD §3.2).
- FR-5.2 ⟳ **Moov path** (bank-number vendor): after one-time vendor-account verification, pay via the standard experience. **Standard delivery 1–3 business days, free.** **Same-day delivery +$4.99 flat**, only if requested **before that day's bank cutoff**; after cutoff, same-day is **not offered and not charged** (BRD §3.3).
- FR-5.3 ⟳ **Check path** (Lob/PostGrid): standard 5–7 business days (per-plan free allowance, then $2.99); expedited 1–2 business days (+$8.99) (BRD §3.3 checks, §6.2).
- FR-5.4 Batch pay: one authorization covers all selected occurrences (840:27360, 840:28151). Consent recorded immutably (text + timestamp + IP + UA).
- FR-5.5 Live processing stages + reference `SWP-YYYYMMDD-NNNN` (840:28543). **Payment-day cancel deadline** = 11:59 PM America/New_York (840:28151) — this is the user-facing cancel window and is **distinct from** the earlier same-day-ACH bank submission cutoff that governs same-day *eligibility and billing* (FR-5.2, NFR-6, §10.9). Do not gate same-day offer/charge on 11:59 PM.
- FR-5.6 ⟳ **Reversal handling:** a transfer that completes, fails, or is **reversed by the receiving bank days later** must automatically update bill status and **notify the customer** (BRD §3.3).
- FR-5.7 Failure flow: reason (e.g. NSF + available balance), late-fee countdown, resolutions retry / change-method / reschedule (840:13131, 841:29250, 841:29742).
- FR-5.8 ⟳ **Non-custodial guarantee:** money never rests in a Swayp-controlled balance between debit and credit; every payment is executed by and traceable to a **named licensed provider** (Stripe/Moov) (BRD §4).
- FR-5.9 State transitions are webhook/task-driven (dedup + out-of-order tolerant); idempotent money-creating endpoints.
- FR-5.10 ⟳ Send/arrival dates and same-day/expedited eligibility computed via **Fed business-day + bank-cutoff calendar** (governs same-day ACH *and* expedited check promises) (BRD §6.2).

### FR-6 Flo — AI cash advisor (E7)
- FR-6.1 Cash context before payment (balance now/after, upcoming bills, next bill) — **math in Python; LLM phrases only**; consent-gated; template fallback (840:27719).
- FR-6.2 Balance projection for a chosen future date (841:29742).
- FR-6.3 ⟳ Flo advisory features may require **explicit opt-in consent** under state privacy law — **pending legal review** (BRD §6).

### FR-7 Dashboard, reports, notifications (E8)
- FR-7.1 Home aggregate: stats, recent bills, vendor preview, Overdue/Due/Upcoming counts (565:4649).
- FR-7.2 Reports filtered by vendor + date range (666:5374); ⟳ includes **1099 reporting** (Standard plan feature, BRD §6.2). Output columns/export TBD (§10).
- FR-7.3 ⟳ Notifications **email only** this release; types BILL_DUE, PAYMENT_FAILED/REVERSED, AUTOPAY_EXECUTED, PAYMENT_ARRIVED, LATE_FEE_WARNING. No SMS/push.

### FR-8 ⟳ Billing & subscriptions (E9 — NEW)
- FR-8.1 **Plans:** Founding $49/mo (first 500 customers, price-locked; 3 team members, 1 bank, unlimited bills/vendors, full Flo, 2 checks/mo), Standard $99/mo (10 team members, unlimited banks, 1099 reporting, priority support, 5 checks/mo), Enterprise (custom; base + add-on rate card; **unlimited team members/seats — no seat cap**; base includes up to 3 entities before the +$79/entity add-on applies).
- FR-8.2 **Per-transaction billing:** standard ACH free/unlimited; same-day ACH $4.99 opt-in (**unbilled after cutoff**); standard check 2 free/mo (Founding) or 5 free/mo (Standard) then $2.99; expedited check $8.99 (all plans).
- FR-8.3 Track and enforce **per-plan allowances** (checks/mo, team seats, connected banks); bill overages correctly.
- FR-8.4 ⟳ **Auto-refund** same-day ACH ($4.99) and expedited check ($8.99) fees when Swayp fails to meet the delivery guarantee (BRD §6.2).
- FR-8.5 **Enterprise add-ons as separate, trackable, invoiceable line items** (base $299; +$79/entity beyond 3; +$99 approval workflow; +$149 ERP sync; +$199 SLA) — not one opaque "custom" charge.

### FR-9 ⟳ Teams & entities (E10 — NEW; Enterprise features later)
- FR-9.1 Team members per account, enforced against plan seat limits.
- FR-9.2 Multi-entity accounts (Enterprise); approval workflows and ERP sync (NetSuite/Sage Intacct/custom API) — later phase.

## 6. Non-functional requirements

| # | Requirement |
|---|---|
| NFR-1 | **No raw bank data (BRD §3.4, hard):** full routing/account numbers are never persisted in Swayp DB, logs, or backups — tokenized at the provider; only masked value + reference id retained. Enforced by schema (no plaintext/encrypted account columns) and a log-scrub gate. |
| NFR-2 | **Masking:** bank identifiers never serialized beyond last-4; masked values rejected as input. |
| NFR-3 | **Non-custodial (BRD §4):** no code path lets funds rest in a Swayp-controlled balance; every movement is attributable to a named licensed provider. Architectural invariant, tested. |
| NFR-4 | **USD only (BRD §3.5):** enforced at the data layer, not just UI; no other currency accepted. |
| NFR-5 | **Consent/audit:** OTPs, ACH authorizations (standing + per-payment/batch) stored immutably with timestamp/IP/UA. |
| NFR-6 | **Correct money math:** Decimal only; Fed business-day + bank-cutoff calendar (America/New_York, DST-safe) governs same-day ACH and expedited check eligibility and delivery promises. |
| NFR-7 | **Idempotency & exactly-once movement:** idempotency keys; processor call keyed before send; reconciliation sweep; webhook dedupe (handles late reversals). |
| NFR-8 | **Provider traceability:** each payment records the executing provider (Stripe/Moov/Lob-PostGrid) and its reference — a regulator question always resolves to a named licensed provider. |
| NFR-9 | **Providers pluggable:** all third parties behind interfaces with mock implementations; no processor name leaks to clients except the legal authorization text. |
| NFR-10 | **API contract:** drf-spectacular docs; `api/v1/`; webhooks versionless. |
| NFR-11 | **Layering & file convention:** views → services → selectors → repositories; per-feature packages ([file-architecture.md](file-architecture.md)). |
| NFR-12 | Availability 99.9%; read p95 ≤ 300 ms (aggregates ≤ 500 ms); payment confirm ack ≤ 1 s (execution async). |
| NFR-13 | **Billing accuracy:** allowance counters and overage/refund calculations are auditable and reconcilable per customer per cycle. |

## 7. Approved providers (BRD §5 — closed list)

No other provider enters the payments/bank-connectivity flow without a new CEO decision. **Provider test (BRD §5.1):** neutral infrastructure ✓ / competes for Swayp's customer relationship ✗.

| Provider | Role |
|---|---|
| **Plaid** | Bank connection, balance, 12-mo history, recurring detection |
| **Stripe** | Payment execution for configured-account vendors |
| **Moov** | Payment execution for bank routing/account vendors (ACH, same-day) |
| **Lob or PostGrid** | Physical check print + USPS mail |
| Anthropic (Flo) · email (Postmark/SES) | Advisor phrasing · transactional email |

**Excluded on record:** Dwolla, GoCardless, Stripe Treasury (superseded); **BILL.com, Melio, and any AP/AR/bill-pay competitor** (BRD §7). *(Market-research-only conversations with an excluded competitor are permitted per BRD §7, provided no data-sharing agreement, pilot, or integration results — this is a business boundary, not a build item.)*

## 8. Release phasing

| Release | Contents (epics) | Gating |
|---|---|---|
| **R1 — Core CRUD** | E1 foundations, E2 auth, E3 vendors, E4 bills, E8.1 dashboard | none (mocks) |
| **R2 — Onboarding & billing** | E5 banking + detection (mock Plaid), E9 billing/plans/allowances, E10.1 team seats, E8 notifications (email) | none (mocks) |
| **R3 — Money movement (mock)** | E6 payments end-to-end (Stripe + Moov + check mocks), E7 Flo (template) | none |
| **R4 — Production rails** | Swap mocks for Plaid/Stripe/Moov/Lob; webhooks live; Flo LLM on | ⟳ **Moov platform application (2–4 wks)** + ⟳ **written legal opinion on the Moov transfer model (Texas + operating states, 1–2 wks)** — hard prerequisites (BRD §4, §6.1); Flo consent legal review (BRD §6) |

## 9. Success metrics
- Onboarding: bank connect → bills imported ≥ 60%.
- ≥ 90% of due occurrences paid/scheduled before due date.
- **0 unmasked bank identifiers** and **0 raw account/routing numbers stored** (automated gates).
- **0 funds held by Swayp** (non-custodial invariant — reconciliation report).
- 0 duplicate money movements; API error rate < 0.5%; schema drift = 0.
- **Billing: 0 mis-billed allowances/overages; 100% of missed delivery guarantees auto-refunded.**

## 10. Open questions (BRD resolved the former blockers; these remain)

**Resolved by BRD:** ACH processor (Stripe+Moov), custody (non-custodial + legal opinion), directory competitor (BILL.com/Melio rejected), currency (USD), payee/vendor account verification (required, provider-run), fraud/OFAC (provider's job).

**Still open:**
1. **Stripe configured-account discovery** — how does Swayp find/search vendors that "have a configured payment account with Stripe" (the 80%-pre-enrolled "Bill Pay Network" UX), now that BILL.com/Melio are rejected and Stripe has no public biller directory? (impl of E3-S7 directory search)
2. ⟳ **12 vs 24 months** — BRD §3.1 says up to **12 months**; screens 836:8984/9052 say **24 months**. Confirm 12 (assumed authoritative) and fix the screens.
3. ⟳ **SMS OTP vs email-only** — BRD scopes SMS out; the OTP screen (1464:16992) offers SMS. Is OTP delivery exempt from the "email only" rule, or email-only this release?
4. Reports output shape (table / CSV / PDF, columns) and **1099 reporting** specifics (form generation vs data export).
5. Late-fee policy: user-entered per vendor (assumed) or inferred?
6. QR payload spec for vendor/bill/invoice QRs.
7. Login "User ID" — no such column exists; add username or treat as email-only copy?
8. Settings screens (bank disconnect, Flo consent, notification prefs, team/billing management) — designs missing.
9. Same-day ACH & expedited-check **cutoff times** and the exact **delivery-guarantee** definition that triggers auto-refunds (BRD says "if Swayp fails to meet the delivery guarantee" — need the SLA per rail).
10. Enterprise **approval workflows** and **ERP sync** — confirm deferred beyond R4.
11. Flo advisory **opt-in consent** requirement — pending legal (BRD §6).
12. Invoice OCR / auto-import — pending CEO decision (BRD §6).

## 11. Design bugs to return to the design team
From [dashboard-plan.md §9](dashboard-plan.md) plus BRD conflicts:
- ⟳ Payment/authorization copy names **GoCardless** (840:28151) and screens imply **Dwolla/Stripe Treasury** — all superseded; the model is **Stripe + Moov**. Update copy.
- ⟳ Bank-connect screens say **"24 months"** (836:8984/9052) — BRD says up to **12**.
- "Discord" → "Discard" (829:4347); State-field placeholder "Suite, unit, etc." (793:1707 etc.); "Save ACH Vendor" on the check drawer (840:16667); receipt vendor mismatch (840:28867); sign-up footer "Create Account" (1464:15936); "$33,7771" (836:8856); Reset-Password screen has no identifier input (1472:18735).
