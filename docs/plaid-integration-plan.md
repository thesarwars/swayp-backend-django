# Plaid integration — status and plan

**Status:** proposed, not started. Every Plaid call named below was run against
the sandbox on 2026-08-19 and the results are recorded verbatim, so nothing
here is planned on an assumption about what the API returns.

**Scope:** the Plaid Role flow in `figma_node_mobile.md` (8 mobile screens) and
the onboarding bank step in `figma_node.md` (node `2113-7090`).

---

## 1. What already exists

The banking endpoints are all built and working. They run against
`integrations/bank_data/mock.py`, which invents banks and transactions —
`BANK_DATA_PROVIDER` defaults to `mock` and there is no `plaid.py`.

So the flow is complete end to end and connects to nothing.

| Figma node | Screen | Endpoint | |
|---|---|---|---|
| `1620-12846` | Connect Your Bank (intro) | static copy | ✅ |
| `1620-12323` | **Select Your Bank** (institution picker) | — | ❌ |
| `1620-12797` | Plaid Secure Login | `POST /banking/link/token`, then Plaid's own SDK | ✅ |
| `1620-12370` | Verifying Account (4 named stages) | `POST /banking/link/exchange`, `GET /banking/scans/<id>` | ⚠️ |
| `1620-12434` | Scanning Transactions (live count) | `GET /banking/scans/<id>` | ⚠️ |
| `1620-12535` | 17 Bills Found (candidates) | `GET /banking/scans/<id>/candidates`, `POST …/import` | ✅ |
| `1620-12687` | What Plaid does / disconnect | static + `DELETE /banking/connections/<id>` | ✅ |
| `1620-12609` | Your bills are ready | `GET /banking/onboarding-summary` | ✅ |
| `2113-7090` | Onboarding step 4 (web) | `link/token`, `link/exchange`, `POST /users/onboarding/skip-bank` | ✅ |

`onboarding-summary` is a field-for-field match with the final screen: total due
this month, due and overdue counts, the masked account, the detected count, and
`rail_readiness.{network_matched, ach_captured, needs_details}` — which is
exactly the three-row "13 vendors → network / ACH routing captured / 4 vendors
need details" block.

⚠️ marks a screen the API can *feed* but not *drive*: see §4.

---

## 2. Sandbox verification

Run against `https://sandbox.plaid.com` with the account's own credentials.
Every method on `BankDataProvider` (`integrations/bank_data/base.py`) was
exercised, because a plan that assumes an endpoint works is a plan that
discovers otherwise halfway through.

| Interface method | Plaid call | Result |
|---|---|---|
| `create_link_token` | `/link/token/create` | ✅ token + expiry |
| `exchange_public_token` | `/item/public_token/exchange` | ✅ access token |
| ↳ accounts | `/accounts/get` | ✅ 3 accounts, masks `0000`/`1111`/`2222` |
| ↳ institution | `/institutions/get_by_id` | ✅ name + logo |
| `get_transactions` | `/transactions/get` | ✅ 48 transactions over 24 months |
| `get_recurring` | `/transactions/recurring/get` | ✅ 7 outflow streams, `MONTHLY`, `MATURE` |
| `get_balance` | `/accounts/balance/get` | ✅ |
| `remove_item` | `/item/remove` | ✅ |
| **`create_processor_token`** | `/processor/token/create` | ❌ **`INVALID_PRODUCT`** |

Also confirmed available, both relevant below:

- `/institutions/search` — ✅ `"chase"` returns Chase and two others
- `/auth/get` — ✅ returns ACH routing and account numbers

### The one failure

`create_processor_token` returns `INVALID_PRODUCT` for **every** processor —
`moov`, `dwolla`, and Stripe's dedicated
`/processor/stripe/bank_account_token/create`. It still fails after re-creating
the item with the `auth` product enabled, and `/auth/get` on that same item
succeeds. So this is not a missing product on the link token.

`INVALID_PRODUCT` on the processor endpoints means **processor tokens are not
enabled on the Plaid account**. That is a per-account entitlement, granted by
Plaid per processor partnership. No amount of code changes it.

**Why this matters beyond one method.** `apps/common/crypto.py` states the rule
the whole money path is built on:

> raw routing/account numbers are **never stored** — not even encrypted. Swayp
> keeps only a masked last-4 + a provider token.

The processor token *is* that token. Without it there are two options, and only
one of them is consistent with the design already shipped:

1. **Get processor tokens enabled** for the chosen rail. Nothing else changes.
2. **Read numbers from `/auth/get` and hand them to the rail directly.** This
   works today, and it means raw account numbers pass through — and would
   likely be stored — contradicting the stated rule and the reason
   `SensitiveCharField` and `mask_last4` exist.

Option 2 should not be taken quietly to unblock a sprint. Flagged for a
decision, not assumed.

---

## 3. Plan — the Plaid provider

Six of the seven interface methods are verified working, so this fills a slot
that `base.py` already specifies rather than reshaping anything.

### 3.1 Dependency and settings

- `plaid-python` in `requirements.txt`.
- `base.py`: `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV` (sandbox /
  production), `PLAID_PRODUCTS`, `PLAID_COUNTRY_CODES`, `PLAID_REDIRECT_URI`.
- `.env` carries the real sandbox values; `.env.example` gets placeholders and
  a comment. Keys never enter a tracked file.
- `production.py` refuses to boot when `BANK_DATA_PROVIDER=plaid` and the keys
  are absent — the same guard `SUBSCRIPTION_BILLING_PROVIDER=stripe` already
  has, and for the same reason: a missing key should stop a deploy, not a
  customer's first bank connection.

### 3.2 `integrations/bank_data/plaid.py`

`PlaidBankDataProvider(BankDataProvider)`, one method per row of the table in
§2. Two mappings need care:

- **`get_recurring`.** Plaid returns `outflow_streams` with `merchant_name`,
  `average_amount`, `frequency` and `last_date`; the interface wants
  `RecurringCandidate(vendor_name, amount, cadence, due_day, occurrences)`.
  `due_day` comes from `last_date`, `occurrences` from the length of
  `transaction_ids`, and `frequency` maps onto the existing cadence enum.
  Streams with `status == "EARLY_DETECTION"` are the ones most likely to be
  wrong, and the screen asks the user to confirm each candidate anyway.
- **`create_processor_token`.** Stripe uses a different endpoint from every
  other processor, so this branches on the processor name rather than passing
  it through. Blocked on §2 regardless — it will be written against the
  documented shapes and left covered by unit tests only, with the sandbox test
  skipped until the entitlement exists.

### 3.3 Registration

`"plaid"` in `_REGISTRY["bank_data"]` in `integrations/factory.py`, imported
lazily — the pattern `stripe` and `fcm` already use, so a deployment running on
mock does not need the SDK installed.

### 3.4 Error mapping

Plaid error codes onto the app's exceptions. The one that matters most is
`ITEM_LOGIN_REQUIRED`: it is the common real-world failure (the user changed
their bank password), it is not a server error, and `BankConnection.status`
already has somewhere to put it. Surfacing it as a 500 would send people to the
logs for a thing the user has to fix themselves.

### 3.5 Tests

- Unit tests with the SDK stubbed. The suite must stay runnable with nothing
  installed and no network — `config/settings/test.py` is explicit that an
  unrunnable suite is indistinguishable from no suite.
- A sandbox integration test behind an env flag, skipped by default. This is
  the one that would have caught the processor-token problem on day one.

---

## 4. The three mismatches between design and backend

Each is a decision for someone, not a bug to fix silently.

### 4.1 History window — 12 months vs 24

Four screens promise 24 months: *"Returns 24 months of history"*, *"Plaid
returned 24 months of history"*, *"Retrieving 24mo transaction history"*, *"From
24mo history"*.

The backend caps at 12. `MAX_MONTHS_HISTORY = 12` in `scan_service.py`,
`months_history` defaults to 12, and `StartScanSerializer` rejects anything
above 12. Sandbox served a 24-month window without complaint.

Either the cap goes to 24 or the copy comes down to 12. Shipping as-is means
the app claims two years and reads one.

### 4.2 Scan progress has no stages

`1620-12370` shows four named stages with Done / Active / Next, and `1620-12434`
shows a live count. The scan model has three states — `RUNNING`, `DONE`,
`FAILED` — and `progress: {is_complete, thin_history}`.

The screen can be built on a timer, but then the bar is fiction: it advances
whether or not anything is happening, and a slow or stuck scan looks identical
to a fast one. Adding a `stages[]` array to the scan detail response is a small
change and makes the screen honest.

### 4.3 Institution picker

`1620-12323` is a native "Select Your Bank" search. Plaid Link already includes
institution search in its own UI, so building this means passing
`institution_id` into link-token creation and maintaining a second search
surface for no functional gain.

`/institutions/search` works (verified), so it is cheap either way — but it is
worth confirming the design intends a native picker rather than illustrating
what Plaid shows.

### 4.4 Dwolla — resolved

Nodes `1620-12846`, `1620-12370` and `1620-12687` all name **Dwolla** as the ACH
executor. The backend implements **Moov and Stripe**, and `file-architecture.md`
says explicitly: *"No `dwolla.py`/`gocardless.py`"*.

**Decided 2026-08-19: the backend is right and the design copy is wrong.** The
API field is rail-neutral (`rail_readiness.ach_captured`), so nothing in the
backend changes. Mobile must not ship screens naming a processor that is not
integrated.

---

## 5. Order of work

1. §3.1–3.3 — provider, settings, registration. Six methods verified; nothing
   blocks them.
2. §3.4–3.5 — error mapping and tests.
3. §4.1 — decide the history window, because it changes what the scan requests.
4. `create_processor_token` — **blocked** on the Plaid entitlement in §2. Write
   it, test it against stubs, leave the sandbox test skipped.
5. §4.2 and §4.3 — out of the agreed scope; listed so they are not forgotten.

The first two steps make the flow real for everything the screens read. Nothing
in the money path can be verified until §2 is resolved.
