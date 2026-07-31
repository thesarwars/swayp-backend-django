# E7 — AI Advisor ("Flo")

Consent, the cash-context line shown before a payment, and balance projection.

← [Index](README.md) · Prev: [E6](e6-payments.md) · Next: [E8 Dashboard & Reports](e8-dashboard-reports.md)

---

## 1. Consent gates everything

Nothing here works until the user has consented. Ask once, store the answer,
and let them revoke.

```
GET    /api/v1/ai/consent/
POST   /api/v1/ai/consent/
DELETE /api/v1/ai/consent/
```

**GET:**

```json
{ "success": true, "message": "Consent state retrieved.",
  "data": { "is_live": false, "consented_at": null,
            "revoked_at": null, "consent_text": null } }
```

**POST** `{ "consent_text": "…the exact text you displayed…" }` — the text is
stored as the record of what was agreed, along with IP and user agent taken
from the request server-side.

**DELETE** revokes. `consented_at` stays and `revoked_at` fills in — the
history is kept, so "did they ever consent" remains answerable.

> **`is_live` is not the same as "consented".** It tells you whether a real
> LLM is wired. It is `false` by default because the advisor runs on a
> deterministic template provider — see §4.

---

## 2. Cash context — the line before a payment

```
POST /api/v1/ai/cash-context/     { "amount": "500.00" }
```

`amount` is **required**; omitting it is a 400.

```json
{
  "success": true,
  "message": "Cash context computed.",
  "data": {
    "text": "Balance $41,200.00. After this payment you'll have $40,700.00, with nothing else due in the next 30 days. Next up: WeWork $3,200.00 due Sep 01.",
    "figures": {
      "balance_now": "41200.00",
      "balance_after": "40700.00",
      "balance_as_of": "2026-07-30T08:38:09.100476Z",
      "upcoming_count": 0,
      "upcoming_total": "0.00",
      "upcoming_window_days": 30,
      "next_bill": { "vendor": "WeWork", "amount": "3200.00",
                     "due_date": "2026-09-01" }
    }
  }
}
```

**Render `text` as-is.** It is already formatted, already rounded, and already
phrased for a user.

**`figures` is there so you don't have to parse `text`.** Use it for the
number chips beside the sentence. Never regex the sentence — the wording
changes with the provider.

⚠️ **Rate limited to 20/min** (`ai_cash_context`). This is the only advisor
endpoint that can reach a paid provider. Call it when the payment drawer
opens, not on every keystroke of the amount field.

`balance_as_of` is when the balance was last refreshed from the bank, not
"now". Show it if the gap could matter.

---

## 3. Balance projection

```
GET /api/v1/ai/balance-projection/?account=<bank_account_id>&date=2026-10-01
```

Both `account` and `date` are **required** — a 400 lists them if missing.

```json
{
  "success": true,
  "message": "Projection computed.",
  "data": {
    "account_id": "495176ad-…",
    "date": "2026-10-01",
    "current_balance": "41200.00",
    "balance_as_of": "2026-07-30T08:38:09.120094Z",
    "outflow_total": "6400.00",
    "committed_total": "0.00",
    "projected_balance": "34800.00",
    "sufficient": true
  }
}
```

**`sufficient` is the answer**; the rest is the working. Branch on it rather
than comparing `projected_balance` yourself — the rule for what counts as
sufficient lives server-side.

`outflow_total` is everything due by that date. `committed_total` is the
subset already authorized and moving. The difference matters: committed money
is gone whatever the user does next.

**422** when the account is unknown or the date is unusable — that is a
"choose a different account/date" message, not a server error.

---

## 4. The advisor is deterministic by default

`LLM_PROVIDER` defaults to `template`: offline, deterministic, and safe to
show a user. No external call is made and nothing is billed.

That is why `is_live` is `false`. When a real provider is switched on, **the
response shape does not change** — only the wording of `text`. So:

- build against `text` + `figures` and you are done either way;
- do not cache `text` across sessions as though it were stable copy;
- do not show "AI generated" chrome conditioned on `is_live` unless product
  asks for it — the sentence is equally real either way.

---

## 5. Order to build

1. **Consent gate** — a one-time modal, plus a revoke control in settings.
2. **Cash context** in the payment drawer. Highest value, one call.
3. **Balance projection** on the account screen, if there is one.

If consent hasn't been given, hide the advisor entirely rather than showing an
empty panel — there is nothing useful to render without it.
