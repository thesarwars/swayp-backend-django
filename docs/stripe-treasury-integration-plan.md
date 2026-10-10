# Stripe Treasury integration — plan

**Status:** plan, nothing built. Written 2026-10-10, after decision D-1
([PRD §0.0](PRD.md)) moved ACH from Moov to Stripe Treasury.
**Basis:** Stripe's documentation as published on 2026-10-10 (sources at the
end), and the current code.

Read §1 first. What Stripe's documentation says changes the plan more than
the code does, and four of its points need a decision before anything is
built.

---

## 1. What Stripe's documentation changes

### 1.1 Treasury in the US is private preview, and v1 is closed to new builds

- **Treasury for platforms (v2)** is **private preview in the US**: "contact
  sales to request access". Without that access none of the v2 endpoints
  below can be called, even in a sandbox.
- **Treasury v1** — the `/v1/treasury/...` API (InboundTransfer,
  OutboundPayment with raw bank details) — is marked **legacy**: "Don't build
  a new v1 integration."

**So the first step is not code: it is getting Swayp's Stripe account into
the US private preview.** Everything below assumes v2.

### 1.2 Each customer becomes a Stripe connected account with full KYC

Each paying customer needs an **Accounts v2 connected account** with the
`money_manager` configuration. Stripe requires, for every customer
(individual or company):

- business legal and display names, entity type, address, phone, product
  description, industry
- owner legal name, **date of birth**, residential address, **SSN or TIN**
- acceptance of the Treasury and Stripe terms

The account **must not use a Stripe dashboard**; **Swayp is responsible for
collecting requirements** (hosted onboarding link or our own form) and is the
**losses collector**. Swayp carries the loss when a pulled ACH debit is
returned after the vendor was already paid.

Today sign-up collects none of the owner details. This is a new onboarding
step for every paying customer, and a support burden when Stripe's review is
inconclusive.

### 1.3 Every vendor becomes a recipient account

v2 pays third parties only to a **recipient-configured connected account**
with a **payout method**. A raw bank number on the payment is not enough.
Each vendor paid by ACH (WeWork, Con Edison, a landlord) becomes a recipient
account under the customer, with a US bank account payout method created
through `POST /v2/core/vault/us_bank_accounts` from its routing and account
number.

To confirm with Stripe: how much the recipient configuration asks about a
vendor who never signs up to anything (a utility). If it needs details we
cannot get, that blocks paying ordinary billers by ACH.

### 1.4 Money takes longer, and same-day ACH is not in v2

| Leg | v2 timing (Stripe docs) |
|---|---|
| Pull from the customer's bank (inbound transfer, ACH) | **3–5 business days** |
| Pay the vendor (outbound payment, ACH standard) | **typically 2–3 business days** |
| **End to end** | **about 5–8 business days** |

The product promises ACH in **1–3 business days**, plus same-day for +$4.99.
v2's US outbound list has ACH standard, wire (same day), RTP (preview) and
push-to-card (preview), and **no same-day ACH**. v1 had same-day only as a
preview.

There are two ways to keep the promise. Both are product decisions:
- **Pre-fund:** customers hold a balance in their financial account and pay
  from it, with only the 2–3 day push. That is a wallet in effect, which the
  product dropped, and it widens the custody question.
- **Change the promise:** ACH becomes "about a week", and same-day becomes
  wire or RTP at a different price.

### 1.5 The Plaid → Stripe token we just enabled may not fit v2

The `btok_…` token Plaid now issues is a **legacy Stripe BankAccount**. v1
accepted it ("an existing BankAccount … set up as a verified
ExternalAccount"). v2's inbound transfers take a **`usba_…` credential**
created either by Stripe's own bank-linking component or by microdeposits
through the API. Nothing in the v2 documentation mentions Plaid tokens.

If v2 will not accept them, every customer links their bank **twice**: once
through Plaid (history, bill detection) and once through Stripe (debits). The
alternatives are worse: microdeposits, which take days, or reading account
numbers from Plaid and sending them to Stripe, which passes raw numbers
through Swayp and contradicts BRD §3.4. **Ask Stripe.**

---

## 2. Gates before code

| # | Gate | Owner | Blocks |
|---|---|---|---|
| G1 | Private-preview access to Treasury for platforms v2 (US) for Swayp's Stripe account, sandbox included | Product → Stripe sales | everything |
| G2 | Written legal opinion covering the Treasury model (PRD D-1) | CEO / legal | production |
| G3 | Answers to §6 (Plaid tokens, vendor recipients, same-day, timing) | Product → Stripe | design of phases 2–4 |
| G4 | Decide the delivery promise: pre-fund vs longer ACH; what replaces same-day | Product / CEO | fees, quote, screens |
| G5 | Accept the onboarding step (owner SSN and DOB) and the platform loss liability for returned debits | Product / CEO | phase 1 |

---

## 3. How a payment would flow (v2, pay-as-you-go)

```
customer's bank ──inbound transfer (3–5d)──▶ customer's financial account ──outbound payment (2–3d)──▶ vendor's bank
       ▲                                         (Stripe Treasury)                     │
       └─ usba_ credential (Stripe link or Plaid?)                       recipient account + payout method
```

1. **Confirm** (unchanged for the user): Swayp creates an inbound transfer
   for the payment amount.
2. Stripe sends `v2.money_management.inbound_transfer` events:
   `bank_debit_processing` → `bank_debit_succeeded` → `available`, or
   `bank_debit_failed` / `bank_debit_returned`.
3. On `available`, Swayp creates the **outbound payment** to the vendor's
   recipient and payout method.
4. Outbound events move it to completed, or to failed or returned.
5. A return on either leg after success becomes the existing `RETURNED` and
   failure paths. A returned **pull after the vendor was paid** is the
   platform loss (§1.2).

---

## 4. What changes in the code

The pieces already fit this flow better than a single-call processor would.

| Area | Today | Change |
|---|---|---|
| `integrations/money_movement/base.py` | `execute()` returns a final result | Add an **in-progress** result: `execute` starts the pull and returns `PROCESSING`; completion arrives by webhook. The engine treats anything not `SUCCESSFUL` as failure today (`execution_service._apply`), so this is the first change. |
| `integrations/money_movement/stripe.py` | absent | New provider: start the inbound transfer, create the outbound payment when funds are available, cancel, look up by idempotency key. Stripe API version pinned to the preview version. |
| Payment stages | `AUTHORIZED → DEBITING → ROUTING → COMPLETED` | Maps cleanly: DEBITING = inbound transfer, ROUTING = outbound payment. Keep the names. |
| `apps/payments/services/webhook_service.py` | Generic `EVENT_STATUS` map keyed on a payment reference | Stripe v2 events carry a **related object id**, not our reference. Store the inbound and outbound ids on the payment (`processor_refs`) and resolve by them. Handle both legs. |
| Webhook view `StripeWebhookAPIView` | HMAC on `Stripe-Signature` | Use Stripe's own signature check (`stripe.Webhook.construct_event`), as Plaid has its own. v2 "thin" events need fetching the related object. |
| Customer onboarding (`apps/users`, `apps/billing`) | no Stripe account per customer | New: create the v2 account, collect requirements (hosted link first), store `stripe_account_id`, gate paying on `money_manager` capabilities being `active`. New onboarding step. |
| `apps/banking` | Plaid link; `BankAccount.processor_refs` | Store the `usba_` credential once linked (Stripe or Plaid route, per G3). |
| Vendors (`VendorPaymentMethod` ACH) | `provider` + `provider_token` | Create a recipient account and a US bank payout method at "add vendor": the server sends the routing and account number to Stripe and stores only the ids and last 4 (VEND-1's server-side tokenization). |
| Fees (`apps/billing/services/fee_service.py`) | same-day $4.99, check fees | Per G4: same-day becomes wire/RTP or goes. The quote (`POST /payments/quote`) and `estimated_arrival` change with it. |
| `apps/common/dates.py` lead and transit days | ACH 1–3 days | Per G4. With pay-as-you-go: about 5–8 business days of lead time for ACH. |
| Cancel | before the deadline; voids at processor | An inbound transfer and an outbound payment can each be cancelled only before submission. `void()` cancels whichever leg is still cancellable. |
| Reconcile job | looks up stuck payments | Look up both legs by id. |
| Mock provider | instant success | Keep it for dev. Add an async mode so the in-progress path is testable without Stripe (also closes PAY-9's slow-stage gap). |

---

## 5. Phases

| Phase | Scope | Needs |
|---|---|---|
| **0. Access and spike** | Get G1. In the Treasury sandbox: create a v2 account, a financial account, a test recipient and payout method; run one inbound transfer and one outbound payment by hand; **test whether a Plaid `btok_` can become a `usba_`** | G1 |
| **1. Engine in-progress path** | Provider interface and execution engine handle `PROCESSING` results and finish by webhook; mock gains an async mode. No Stripe yet. | nothing (can start now) |
| **2. Customer accounts** | v2 account per customer, hosted onboarding link, capability status webhook, "can pay" gate | G1, G5 |
| **3. Customer bank credential** | `usba_` from Stripe linking or Plaid (per the spike) | G1, G3 |
| **4. Vendors as recipients** | recipient account and payout method at add-vendor; existing ACH vendors backfilled | G1, G3 |
| **5. Stripe provider** | inbound → outbound, webhooks for both legs, cancel, reconcile, returns | phases 1–4 |
| **6. Fees and dates** | delivery promise, same-day replacement, quote and fee changes | G4 |
| **7. Production** | live keys, live Plaid–Stripe connection, legal opinion | G2 |

**Phase 1 is the only thing worth building before G1.** It's useful whatever
Stripe answers, and it fixes the engine's "anything not successful is a
failure" assumption.

---

## 6. Questions to take to Stripe

1. Can Swayp get **Treasury for platforms (v2) private-preview access in the
   US**, sandbox first? What are the commercial terms (financial account
   fees, per-transfer fees)?
2. Can a **Plaid processor token** (`btok_`) become a v2 `usba_` credential
   for inbound transfers, or must customers link through Stripe's component?
3. For paying ordinary billers (utilities, landlords): what does a
   **recipient-configured account require** when the vendor never signs up?
   Can the platform create it from a name and bank details alone?
4. Is **same-day ACH** available for v2 inbound transfers or outbound
   payments in the US? If not, what is the fastest reversible option?
5. Real-world timing for **inbound (3–5 days) plus outbound (2–3 days)**:
   can funds be released early for low-risk customers, and at what loss
   exposure?
6. With `losses_collector: application`, what reserves or limits will
   Stripe require of Swayp?
7. Can **Swayp's existing subscription billing** (Stripe Billing on the
   platform) coexist with the Treasury platform setup on the same account?

---

## Sources

- [Treasury for platforms — availability](https://docs.stripe.com/treasury/connect)
- [Connected accounts for Treasury v2 — eligibility, capabilities, requirements, recipient payout methods](https://docs.stripe.com/treasury/connect/account-management/connected-accounts)
- [Fund a financial account — inbound transfers, `usba_` credentials, timing](https://docs.stripe.com/treasury/connect/moving-money/fund-a-financial-account)
- [Pay others — v2 outbound payments, recipients, US methods](https://docs.stripe.com/treasury/connect/moving-money/out-of/outbound-payments)
- [v1 InboundTransfer (legacy)](https://docs.stripe.com/treasury/moving-money/financial-accounts/into/inbound-transfers)
- [v1 OutboundPayment (legacy)](https://docs.stripe.com/treasury/moving-money/financial-accounts/out-of/outbound-payments)
