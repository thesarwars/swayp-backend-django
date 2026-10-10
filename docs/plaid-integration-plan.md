# Plaid integration — status and plan

**Status:** §3 built (2026-08-25). Every Plaid call named below was run against
the sandbox and the results are recorded verbatim, so nothing here rests on an
assumption about what the API returns.

Building it surfaced two things the probing had not — see §2.1. Both are
first-connect behaviour, both would have hit every user, and neither is
visible from the documentation alone.

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

### 2.1 What only appeared once it ran

Two conditions that a one-shot probe misses, because they are properties of a
*freshly linked* item:

**`PRODUCT_NOT_READY`.** Plaid pulls an item's history asynchronously after the
exchange. A scan started immediately — which is exactly what onboarding does —
asks for history that has not arrived. `ScanService` caught it under
`except Exception` and marked the scan `FAILED`, so **every user's first
connection would have ended on an error screen** with nothing actually wrong.
Now `BankDataNotReady`, and the scan stays `RUNNING` so a retry finishes it.

**Partial history without an error.** On a second run `get_transactions`
*succeeded* and returned 17 transactions covering one month — not the 24 the
screens promise. A fresh item answers with whatever has landed so far and no
error at all. Detection over one month of data finds almost nothing, and the
"17 bills found" screen would show a near-empty list that looks like a real
answer.

**Both are handled now** (2026-08-25). The scan started at connect time stops
on `BankDataNotReady` and stays `RUNNING`; Plaid's
`TRANSACTIONS/HISTORICAL_UPDATE` callback re-queues it once the full window is
there. `INITIAL_UPDATE` is deliberately ignored — it carries only 30 days, and
acting on it is precisely the partial-history bug.

Wiring it meant discovering that **Plaid fits none of the shared webhook
assumptions**, and each mismatch rejected every one of its callbacks:

| Assumption | Plaid | Result before |
|---|---|---|
| HMAC-SHA256 of the raw body | ES256 JWT, key fetched by `kid` | signature mismatch |
| payload carries `id` / `event_id` | carries neither | "Payload has no event id" |
| event maps to a payment status | is about data readiness | ignored |

`WebhookAPIView.verify()` and `.handle()` are overridable now, defaults
unchanged for the four payment processors. The JWT check pins `alg` to ES256
(accepting the token's own `alg` is the classic forgery), compares
`request_body_sha256` against the body, and rejects anything older than five
minutes. The event id is synthesised from the item, the code and a body hash,
so Plaid's retries — identical bytes — dedupe.

`PLAID_WEBHOOK_URL` is now sent on every link token. It is registered **per
item at link time**, not configured in Plaid's dashboard, so an item linked
while it is empty never reports readiness and its scan waits forever; the
provider logs a warning rather than omitting it quietly. Verified: sandbox
accepts a link token carrying it.

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
  production), `PLAID_PRODUCTS`, `PLAID_COUNTRY_CODES`, `PLAID_REDIRECT_URI`,
  and `PLAID_ANDROID_PACKAGE_NAME` (sent instead of the redirect URI when
  `link/token` is asked for `platform: android`).
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

### 4.1 History window — resolved: 24

**Decided 2026-08-25: 24 months.** `MAX_MONTHS_HISTORY = 24`, the model default
is 24 (migration `0002`), and `StartScanSerializer` accepts up to 24.

Worth recording that this **overrides the BRD rather than following it**. BRD
§3.1 says "up to 12 months" and PRD §11 listed the 24 on screens 836:8984/9052
as a design bug to send back. The screens won: they all promise 24, Plaid
serves that window, and the requirement moved to match the design.

The mock provider still generates 12 months of canned history, so a
mock-backed scan requests 24 and receives 12. That is honest for a fixture and
does not affect the Plaid path.

### 4.2 Scan progress — resolved

`1620-12370` shows four named stages with Done / Active / Next, and `1620-12434`
shows a live count. The scan model has three states — `RUNNING`, `DONE`,
`FAILED` — and `progress: {is_complete, thin_history}`.

**Built.** `progress.stages[]` on the scan detail carries four rows —
`connected`, `verifying`, `history`, `detecting` — each `done` / `active` /
`pending` / `failed`, derived from `transactions_scanned` and `detected_count`
rather than from a clock. Exactly one is ever active, and a failed scan shows
which step it stopped on rather than reporting everything done or everything
pending. The client renders the list; it does not decide the sequence.

### 4.3 Institution picker — resolved

`1620-12323` is a native "Select Your Bank" search. Plaid Link already includes
institution search in its own UI, so building this means passing
`institution_id` into link-token creation and maintaining a second search
surface for no functional gain.

**Built** as `GET /api/v1/banking/institutions?search=`, scoped to
`PLAID_PRODUCTS` so the picker cannot offer a bank that then fails at link
time. The mock searches its canned four, so the screen works offline. A
provider that cannot search raises rather than returning `[]` — an empty list
reads as "no banks match" and sends the user hunting for a typo.

The caveat above stands: Plaid Link searches institutions in its own UI, so
this is only needed by a client drawing its own list.

### 4.4 Dwolla — resolved

Nodes `1620-12846`, `1620-12370` and `1620-12687` all name **Dwolla** as the ACH
executor. The backend implements **Moov and Stripe**, and `file-architecture.md`
says explicitly: *"No `dwolla.py`/`gocardless.py`"*.

**Decided: the backend is right and the design copy is wrong.** Confirmed
2026-08-25 — *"no need dwolla, we will never use dwolla"*. The codebase already
holds that line in more than one place: `integrations/__init__.py` and
`apps/common/enums.py` record the exclusion, and
`apps/common/tests/test_integrations.py` has a `BANNED` list that fails if a
Dwolla provider ever appears. The API field is rail-neutral
(`rail_readiness.ach_captured`), so nothing in the backend changes. Mobile must
not ship screens naming a processor that will never be integrated.

---

## 4b. Built

- `integrations/bank_data/plaid.py` — all seven methods, error translation.
- `BankDataProviderError` / `BankReauthRequired` / `BankDataNotReady` in
  `bank_data/base.py`.
- `ScanService` tells the three apart: not-ready stays `RUNNING`, reauth marks
  the *connection* `ERROR` with a message addressed to the user, anything else
  fails as before.
- `PLAID_*` settings, lazy registration in `factory.py`, `plaid-python` in
  requirements, `production.py` refusing to boot on `plaid` without keys or
  with `PLAID_ENV != production`.
- 26 tests: 21 stubbed (offline), 5 on the scan mapping, 1 live sandbox test
  behind `PLAID_SANDBOX_TESTS=1`.

Not built: the webhook wait (§2.1), and §4.1–4.3 below.

## 5. Order of work

1. ~~§3.1–3.5 — provider, settings, registration, error mapping, tests.~~ Done.
2. ~~The `HISTORICAL_UPDATE` webhook (§2.1).~~ Done.
3. ~~§4.1 — the history window.~~ Done: 24, overriding the BRD.
4. **Deploy configuration.** Four values the code cannot supply itself, all
   on the server and needing a restart: `PLAID_CLIENT_ID`, `PLAID_SECRET`,
   `PLAID_WEBHOOK_URL` (items linked without it never report readiness), and
   `MOOV_WEBHOOK_SECRET` — `/webhooks/moov` still answers *"No webhook secret
   configured for MOOV."*

   Both mounts now answer, so a dashboard configured against
   `/api/v1/webhooks/<processor>` works as well as the canonical versionless
   path. `reverse()` still returns the versionless one.
5. ~~§4.2 scan stages and §4.3 institution search.~~ Done.
6. `create_processor_token` — **blocked** on the Plaid entitlement in §2.
   Written to the documented shapes, stub-tested, sandbox test skipped. This
   is the only remaining code-level blocker, and it is not ours to unblock.
7. **Moov's signature scheme**, unverified. The shared HMAC that Plaid turned
   out not to use is the same one `MoovWebhookAPIView` assumes. Worth checking
   against Moov's docs before counting that integration as wired — the
   override points now exist either way.

### The webhook is no longer mandatory

`sync_transactions` now retries a not-ready scan on its own — 30s doubling to
roughly 30 minutes, then FAILED with a message a person can act on. The
webhook remains the better path (it resumes the moment the data lands, instead
of waiting out a backoff), but a deployment without `PLAID_WEBHOOK_URL` no
longer leaves scans hanging forever.

Step 1 makes the flow real for everything the screens read. Step 2 makes it
*correct* for the first connection, which is the only one every user makes.
Nothing in the money path can be verified until §2 is resolved.
