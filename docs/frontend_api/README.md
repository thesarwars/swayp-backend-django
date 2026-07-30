# Frontend API Guides — one per epic

How to implement the frontend against each epic's API. One file per epic, in
the order you should build them.

Every response body in these files was captured from the running API.

| Epic | Guide | What you build |
|---|---|---|
| **E1** | [Foundations](e1-foundations.md) | conventions every other guide assumes — envelopes, dates, money, idempotency |
| **E2** | [Authentication](e2-authentication.md) | register, OTP, login, password reset, profile, onboarding wizard |
| **E3** | [Vendors](e3-vendors.md) | payees, payment methods, directory search, QR |
| **E4** | [Bills](e4-bills.md) | the bill wizard, occurrence list, summary, invoice |
| **E5** | [Banking](e5-banking.md) | bank link, transaction scan, bill detection, import |
| **E6** | [Payments](e6-payments.md) | the pay flow, batches, cancel, failure recovery |
| **E7** | [AI Advisor](e7-ai-advisor.md) | consent, cash context, balance projection |
| **E8** | [Dashboard & Reports](e8-dashboard-reports.md) | home, reports, 1099, notifications |
| **E9** | [Billing](e9-billing.md) | plans, trial, card collection, allowances, fees, invoice |
| **E10** | [Teams](e10-teams.md) | seats, roles, invitations, entities |

**Base URL:** `/api/v1/` · **Interactive schema:** `/api/docs/`

---

## Build in this order

Each step has real data by the time you reach it.

```
E2  auth        register → OTP → login
E2  onboarding  business → plan → payment → bank
E5  banking     scan → review detected bills → import   ← fastest path to data
E4  bills       list, detail, summary
E3  vendors     list, detail, payment methods
E6  payments    select → authorize → poll → receipt
E8  dashboard   home, reports, notifications
E9  billing     plan screen, allowances, fees, invoice
E10 teams       members, invites, entities
```

**Start with onboarding, then the bank scan.** One bank link produces four
vendors and four bills with real schedules, so every screen after it has
something to render. Building bills or vendors first means staring at empty
states.

---

## Read this before anything else

### There are three response envelopes, not one ⚠️

The API is not consistent. Write one unwrap helper and use it everywhere.

| Shape | Where |
|---|---|
| `{ "success", "message", "data" }` | auth, bills, banking, billing, teams, users, categories |
| `{ "items": [...], "pagination": {...} }` | `vendors/`, `vendors/<id>/payment-methods/`, `directory-search/` |
| a bare object, no wrapper | vendor create/detail/update, `vendors/qr/decode/` |

Some list endpoints put `data` **and** `pagination` at the top level
(`bills/occurrences/`, `notifications/`, `payments/history/`, `reports/`).

Success responses in the second and third shapes have **no `success` field**;
errors always do. **Branch on the HTTP status, never on the body.**

```js
const unwrap = (body) =>
  body?.data  !== undefined ? body.data  :
  body?.items !== undefined ? body.items :
  body;
```

### Status codes worth handling once, globally

| Status | Meaning | What to show |
|---|---|---|
| 400 | validation | field errors from `errors` |
| 401 | token missing/expired | refresh, then retry |
| **402** | **plan limit reached** | **upgrade prompt** |
| **403** | **your role forbids it** | **"ask your admin"** |
| 404 | not found, **or owned by someone else** | not found |
| 405 | not supported yet (report export) | the message |
| 409 | idempotency conflict / state conflict | the message |
| 422 | QR unreadable | "scan again" |
| 429 | rate limited | honour `Retry-After` |
| 501 | deferred this release (SMS) | the message |
| 503 | billing provider unreachable | "try again" |

**402 and 403 are different problems.** 402 is a full plan and money fixes it;
403 is a role and nothing does. Sending a 403 to the pricing page is a dead
end; sending a 402 to "ask your admin" hides a sale.

**402, 403 and 503 carry `message` only — no `errors` object** — and every one
of those messages is written to be shown to the user verbatim.

### Money, dates, ids

Amounts are decimal **strings** (`"3200.00"`), USD. Dates are `YYYY-MM-DD`,
timestamps ISO-8601 UTC, ids UUIDs.

Exception: in **bill detail**, `overdue_amount`, `days_overdue` and
`total_paid` come back as **numbers**. Coerce.

### The account is not the user

After someone accepts a team invitation their requests operate on the
**inviting account**. `GET /teams/me/` returns that `account_id` — use it as
your cache key, not the user id, or two teammates will thrash each other's
data. See [E10](e10-teams.md).

---

## Not built — do not design around these

| Gap | Note |
|---|---|
| SMS OTP | Designed, deferred (BRD §1.2). `channel=SMS` returns **501**. |
| SSO (Google / Microsoft / Windows Hello) | On the Sign In design, not built. |
| Accountant portal | On the Sign In design, not built. |
| Report export | Format undecided; `?export=` returns **405**. |
| Approval workflows, ERP sync | E10-S4, deferred beyond R4. Add-ons sell but are inert. |
| Proration | A mid-cycle plan change takes effect at the new price with no credit. |
| Invoice history | Current cycle preview only. No past invoices, no PDF. |
| Change password from Settings | Only the OTP forgot-password flow exists. |
| Change email or phone | Read-only. No verified change flow. |

## Known design/spec conflicts, already resolved

| Design says | Reality | Why |
|---|---|---|
| 4 plans incl. Solo $29 | **3 plans** | BRD §6.2 is the source of truth |
| "Unlimited team members" on every plan | **3 / 10 / unlimited** | same |
| Founder "first 100" (body) | **500** | the design's own badge and the BRD both say 500 |
| Onboarding "Step _n_ of 5" | **4 steps** | design error; read `total_steps` from the API |
