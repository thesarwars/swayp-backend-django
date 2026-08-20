# Mobile API Gap Report

**What this is:** a read of the mobile redesign in Figma (`docs/figma_node_mobile.md`, 18 sections,
~120 nodes) against the API this backend actually serves today — which was built for the web design
(`docs/figma_node.md`, `docs/epics/`, `docs/frontend_api/`).

**Nothing in the codebase was changed.** This is a report only.

---

## How to read the confidence markers

Every finding carries one:

| Marker | Means |
|---|---|
| **[V]** | I verified it myself against the code in this session — file and line cited. Treat as fact. |
| **[R]** | Reported by a screen-reading pass, **not** independently verified. Confirm before acting. |

The adversarial verification pass was supposed to check every **[R]** item and did not run — the
account hit its session limit mid-run. So **[R]** items are raw claims. The most common failure mode
for a claim like this is "the field exists under a different name", and one such correction already
surfaced during spot-checking (see *Bills list tabs* below, where a claimed blocker turned out to be
a much smaller gap). Budget for some **[R]** items dissolving on contact.

## Coverage

| | |
|---|---|
| Sections read in full | 10 of 18 |
| Sections read by sampling | 4 (Pay, Add Bill, Plaid Role, Add Bill QR — key screens only) |
| Sections not read | Add Bill part 2; the cross-cutting platform sweep died mid-run |
| Screens described | ~60 of ~120 nodes |

Findings below are **not** a complete list. The unread screens are mostly repeats of flows that were
read (the QR/scan screens duplicate Add Vendor — Scan heavily), so the blockers are unlikely to move
much — but treat "no finding here" for Add Bill part 2 as "not looked at", not "clean".

---

## The short version

Six things stop the mobile app from being built as designed. Three are real backend gaps, three are
the design asking for a product Swayp deliberately isn't.

1. **Sign-up can't succeed.** The mobile Create Account form has no person-name field; `register/`
   rejects the payload. **[V]**
2. **The phone can't receive notifications.** No device-token registration exists, and push has no
   delivery adapter by construction. **[V]**
3. **"Scan a bill" only reads QR codes.** Photographing a paper bill with no QR returns 422. There
   is no OCR anywhere. **[V]**
4. **The Home screen is built on a wallet.** Balance, deposit, transfer — Swayp never holds money,
   and those routes don't exist and won't. **[R]** — but the invariant is documented and hard.
5. **Vendor ACH capture sends raw routing + account numbers**, which the API refuses at the
   boundary by design, and there's no mobile tokenization path. **[R]**
6. **The plan catalogue on the phone is a different product** — wrong plan count, wrong prices,
   annual billing that doesn't exist. **[R]**

Separately, the read turned up **three genuine defects in shipped code** that are not mobile
concerns at all. They are at the end, and the reset-password 500 is worth fixing this week.

---

## 1. Blockers — mobile cannot ship without these

### 1.1 Create Account has no name field, so registration 400s **[V]**

The mobile form (`1617:9680`) collects Business Name, Business Address, Email, phone, POC, "Bill
Corresponding Data", Password, Confirm Password. There is no first name, last name, or full name
anywhere on it, and no second page — the only other button on the frame is `hidden="true"`.

`register/` requires one:

- [user_registration.py:164-174](apps/authentication/api/serializers/user_registration.py#L164-L174) raises
  `{"full_name": "Provide full_name, or first_name and last_name."}` when both forms are absent.
- [registration_service.py:30](apps/authentication/services/registration_service.py#L30) pops `full_name`
  into a non-null `Profile.full_name`.

**Fix — server side, cheapest:** when `full_name`/`first_name`/`last_name` are all absent and
`account_type` is BUSINESS, fall back to `poc_name`. The serializer already does the reverse
(defaults `poc_name` to `full_name`), so this closes the loop and the mobile form works unchanged.

**Or — design side:** add a name field. Worth asking, because `full_name` feeds the dashboard
greeting ("Good Morning! / Dianne Russell" on `1620:8843`), and a POC name is not always a person.

### 1.2 No push notifications, and no way to register a device **[V]**

The app has a notification centre (`1620:9394`, `1620:9463`) and a bell on Home. On a phone that
implies push. The backend cannot deliver it and cannot even be told where to send it:

- **No device-token model or route exists.** Nothing in `apps/` registers an APNs/FCM token.
- `push` is a stored column but is `supported: false` **by construction** — there is no adapter class
  to register ([channels/__init__.py](apps/notifications/channels/__init__.py),
  [channels/base.py:18-23](apps/notifications/channels/base.py#L18-L23)).
- `PATCH notifications/preferences/` **actively refuses** to set it:
  ["push cannot be switched on — there is no delivery adapter this release"](apps/notifications/api/views/preference.py#L50-L51).

**Needs:** a device registration endpoint (`POST notifications/devices/`, token + platform + app
version, unique per token, revoked on logout), a push channel adapter, and flipping `supported` once
the adapter is registered. The preference matrix already renders from `channels`, so the settings
screen lights up on its own the moment the adapter exists — no client change.

**Note:** this is deferred per BRD §1.2, so it is a *scheduling* decision, not an oversight. But an
in-app-only notification centre on a native app is a strange product, and the mobile design does not
appear to know push is off.

### 1.3 "Scan" is QR-only — there is no OCR **[V]**

Two whole flows are built on photographing a bill: *Add Vendor — Scan* (9 screens) and *Add Bill — QR
code Scan* (10 screens), plus a "Capture" action on Home.

The only image endpoints in the entire backend are the two QR decoders, and they run a QR decode, not
text extraction:

```python
# apps/vendors/services/qr_decoder.py:16-27
img = Image.open(BytesIO(image.read()))
decoded = decode(img)                    # pyzbar
if not decoded:
    raise ValueError("Unable to decode QR code.")
```

Photograph a paper utility bill with no QR square on it and the user gets a 422. The screens read as
"point your camera at the bill" — that only works for bills that carry a QR code, which in the US is
a minority of them.

**Decide first, then build:** if "scan" means *QR*, the design copy and illustrations need to say so
and the flow needs a manual fallback. If it means *photograph any bill*, that's an OCR/document-
extraction service (vendor name, account number, amount, due date) — a substantial new capability,
not a field addition, and it should return `provenance` per field the way the QR parser already does
so the user confirms before saving.

### 1.4 Home is designed around a wallet Swayp does not have **[R]**

The Home screens (`1620:8843`, `1620:9066`) show a balance card and money-movement affordances.
Payments E6 §1.3 is unambiguous:

> Swayp never holds the money. There is no Swayp balance, no top-up, no wallet — that subsystem was
> deleted and its routes 404. **Never build a "balance" UI.**

This is a hard product invariant, not a missing endpoint. **No backend work should be scheduled
against it.** The card needs to be reframed as the *funding account* balance (which
`banking/accounts/` does serve, masked) or removed.

⚠️ The two Home frames also ship **different bottom tab bars**, and one includes a **"Location"** tab
with nothing behind it. **[R]** Needs a design decision before either is built.

### 1.5 Vendor ACH capture sends raw bank numbers **[R]**

The manual and directory vendor flows collect a routing number and an account number and submit them.
The API refuses raw numbers at the boundary by design (BRD §3.4) — you must send a processor token
plus the last four. There is no tokenization endpoint a **native** client can call; the existing path
assumes a browser SDK.

**Needs a decision:** either a mobile tokenization endpoint / SDK integration, or the mobile ACH form
is replaced by the same Plaid link flow used elsewhere. This blocks "add a vendor by bank details"
entirely on mobile. Verify the claim first — it is **[R]** — but the underlying rule is documented and
firm, so the shape of the problem is real.

### 1.6 Plan and Subscription sells a different product **[R]**

Reported conflicts on `1620:9836` / `1620:9706` / `1620:9865` / `1620:9765` / `1620:9788`:

- plan names, prices and tier count contradict the three plans `billing/plans/` sells;
- **Enterprise is priced per year** — there is no annual billing period in the backend at all;
- **"Billing History"** has no backing endpoint (current-cycle preview only — a known gap);
- no endpoint returns **the card on file** ("Visa ending in 3654"); `payment-method/setup/` mints a
  SetupIntent and nothing reads back;
- no fields for **feature bullet copy**, **discounted price**, or a **"15% OFF"** badge.

README already records that the web design had a 4-plan/unlimited-seats conflict resolved in favour
of the BRD. The mobile design appears to have **reintroduced it**. Resolve with product before
building; then the real backend items are *card-on-file read*, *invoice history*, and *annual
billing* — each substantial.

---

## 2. Real gaps worth building (not blockers)

### 2.1 A payment "quote" before the payment exists **[V, from the design]**

*Schedule Payment* (`1620:14399`) renders, for a date the user is *considering*:

> "Payment sent Dec 18 — Arrives Dec 20 via ACH Standard, 3 days after due date — No late fee expected"

Today `initiated_date` / `estimated_arrival` only come back from `POST /payments/`, which **reserves
the payment** and flips occurrences to SCHEDULED. You cannot ask "what would happen if I sent it on
the 18th?" without creating something.

**Proposal:** `POST payments/quote/` — same inputs as create (`occurrence_ids`, `rail`,
`scheduled_for`), returns `initiated_date`, `estimated_arrival`, `cancellation_deadline`, `fee`, and
a late-fee outlook, and **creates nothing**. The business-day calendar and fee logic already exist;
this is a read-only re-use of them.

The projected-balance half of that same screen is **already covered** by
`GET ai/balance-projection/` — it matches the design almost word for word.

### 2.2 Bills list tabs have no counts **[V — and this corrects a claimed blocker]**

The mobile Bills screen (`1620:12120`) shows **Active (14) · Overdue (9) · Schedule (4) · Paid (1)**
with a "Total Due this month $18,450" header.

A screen-reading pass called this a blocker ("no filtering"). **That is wrong** — filtering exists:
[occurrences.py:25](apps/bills/views/occurrences.py#L25) documents
`status=UPCOMING|DUE|OVERDUE|SCHEDULED|PAID`, and all five values are real
([enums.py:79-84](apps/common/enums.py#L79-L84)).

The actual, smaller gap:
- **No per-tab counts.** `dashboard/home/` returns `pay_panel.tabs` with `overdue`/`due`/`upcoming`
  only — no `scheduled` or `paid`. Rendering four counted tabs costs four extra calls.
- **"Active" is not a status.** It appears to mean "everything not paid". No aggregate exists.

**Proposal:** extend `pay_panel.tabs` (or `bills/summary/`) with `scheduled`, `paid` and `active`
counts. Small change, removes 4 round-trips from the app's second-most-used screen.

### 2.3 Profile fields the mobile Account screens need **[V]**

- **Avatar: `profilePicture` is a phantom field.** `dashboard/profile-summary/` serializes it from
  `getattr(profile, "profile_picture", None)`
  ([dashboard_service.py:32-34](apps/dashboard/services/dashboard_service.py#L32-L34)) — and no
  `profile_picture` field exists on any model. The test asserts it is `None`
  ([test_profile_summary.py:52](apps/dashboard/tests/test_profile_summary.py#L52)). It can never be
  anything else. Mobile shows an avatar on Home, Account Profile and Security.
  **Needs:** a real field + the backend's **first** file-upload endpoint (only the QR decoders accept
  multipart today) + storage config.
- **Date of Birth and Gender do not exist** — zero hits across `apps/`. The Edit Profile screen
  collects both.
- **No username / `@handle`** anywhere (the Security screen shows `@tianasaris`).

### 2.4 Notification centre shape **[R]**

- Tabs (Transactions / Promotion) have **no filter param** on `GET notifications/`.
- **Nothing in the product ever creates a PROMOTION notification** — the tab would always be empty.
- The Account Profile notification screen is **six global switches**; the API is a 10-type × 4-channel
  matrix with no master switch. These need reconciling in one direction or the other.
- "Phone Call" appears as a channel the backend has never heard of.

### 2.5 Support chat has no backend at all **[R]**

The Support screen (`1620:9322`) is a chat composer, with voice input and no attachment path. There
is no messaging, ticketing, or attachment storage in this backend. Either integrate a third-party
support SDK client-side (no backend work) or scope a real feature — but it is currently drawn as if
it exists.

### 2.6 Smaller items **[R]**

| Gap | Endpoint |
|---|---|
| Provider card's "B/A No" + account name not modelled | `dashboard/home/` `vendors_preview` |
| `vendors_preview` has no date for the card's "Last Date" | `dashboard/home/` |
| Payment history has no guaranteed recipient name (`providerName` is nullable and null on the occurrence-driven flow the app uses) | `payments/history/` |
| No transaction-type field for History's four tabs | `payments/history/` |
| Bill Type tiles can't filter — no category filter on occurrences | `bills/occurrences/` |
| "Track your Payment" can't list in-flight payments in one call | `payments/history/?status=` |
| Vendor create can't record which directory entry was chosen | `POST vendors/` |
| Directory search returns no logo; create accepts none | `vendors/directory-search/` |
| Category crosses the wire as a name one way, a bare UUID the other | vendors endpoints |
| `account_type` (Checking/Savings) writable but never readable back | vendor payment methods |
| No idempotency on vendor create — retry duplicates | `POST vendors/` |
| Reset does not clear the login lockout, so post-reset sign-in can still be refused | `auth/reset-password/` |
| Logout revokes every device, not just this phone; no session list | `auth/logout/` |
| No language field; server copy is English-only | `users/profile/` |

`vendors/` create also requires a `category` the mobile flow never collects, and
`apps/bill_categories/migrations/` contains only `0001_initial.py` — **no seed data**, so there may be
no valid category to send. **[V for the missing seed; [R] for `category` being required.]**

---

## 3. Design/spec conflicts — resolve with product, not with code

These are not backend work. Someone has to decide.

| Design says | Backend does | Where |
|---|---|---|
| Plaid returns **24 months** of history **[V]** | scan is **12 months** (`months_history: 12`) | `1620:12846` vs E5 |
| **"Dwolla"** knows where to pull from **[V]** | — | `1620:12846` |
| Processed via **"GoCardless"** **[V]** | — | `1620:15329` |
| Vendor methods report provider **"MOOV"**; "Stripe" named across vendor screens | API deliberately never returns a processor brand outside `authorization_text` | E3 / `1620:11982` |
| Sign-in accepts **"Email or User ID"** | no user-id column exists; `USERNAME_FIELD = "email"` — already logged as an open question in epic-2 | `1617:9372` |
| **"Send OTP via SMS"** offered in two places | `channel=SMS` → **501** | `1617:9628`, forgot-password |
| Sign-up drops terms/signatory checkboxes | they are stored **legal artifacts** with timestamps | `1617:9680` |
| "~80% of US vendors pre-enrolled, searched in real time" | four hard-coded seed rows | `1620:11982` |
| Vendor trust badge | `payee_verified` is never set — always `false` | E3 |

**The three processor names are the sharpest one.** The mobile design hardcodes **Dwolla** on the bank
screen and **GoCardless** on the payment confirm screen, while vendor payment methods report
**Moov**. The client must render `authorization_text` **verbatim** from the API — it is the stored
record of what the user agreed to and it names the licensed provider because NACHA requires it. The
design's baked-in copy must not ship.

**Good news:** the mobile Sign In screen has **dropped** the Google / Microsoft / Windows Hello
buttons and the Accountant Portal link that the web design showed and that were never built. That
conflict is gone. **[R]**

---

## 4. Defects found on the way — not mobile issues, fix anyway

### 4.1 A wrong or expired password-reset OTP returns HTTP 500 **[V]**

[reset_password_service.py:28-41](apps/authentication/services/reset_password_service.py#L28-L41) raises
**bare `Exception`**:

```python
if not user:                          raise Exception("OTP not found.")
if otp_obj.expires_at < timezone.now(): raise Exception("OTP expired.")
if not OTPService.verify_otp(...):    raise Exception("Invalid OTP.")
```

DRF's handler doesn't recognise a bare `Exception`, so
[exception_handler.py:8-13](apps/common/exception_handler.py#L8-L13) falls through to
`"Internal server error."` with **status 500**.

Every user who fat-fingers a reset code gets a 500. Registration and login handle the identical case
correctly, as serializer `ValidationError`s returning 400 with `{"otp": "Invalid OTP."}`
([user_registration.py:232-247](apps/authentication/api/serializers/user_registration.py#L232-L247),
[user_login.py:100-116](apps/authentication/api/serializers/user_login.py#L100-L116)). Reset is the
only one that doesn't. **Fix: raise `ValidationError({"otp": ...})` to match.**

### 4.2 Password reset accepts a weaker password than registration **[V]**

`ResetPasswordSerializer.password` is `CharField(min_length=12)` and nothing else
([password_reset.py](apps/authentication/api/serializers/password_reset.py)). Registration enforces
12+ **plus** uppercase, lowercase, digit and special character. So `aaaaaaaaaaaa` is refused at
sign-up and accepted at reset — a documented policy, bypassable by anyone who resets.

### 4.3 `forgot-password/` confirms whether an email is registered **[V]**

`ForgotPasswordSerializer.validate_email` raises `"User does not exist."` on an unknown address —
an account-enumeration oracle on an unauthenticated endpoint.

The phone-login endpoint next door goes out of its way to avoid exactly this ("If that number is
registered, a code has been sent" — identical whether or not it exists). Forgot-password should
match: always 200, always the same message.

The mobile flow makes this worse: its reset screens have **no email field and no error slot** to show
the message in anyway. **[R]**

---

## 5. Already covered — don't rebuild these

Worth knowing, because several mobile screens look new and aren't:

- **Pay flow** — the mobile Payment Summary, Confirm & Send, Processing and receipt screens map
  cleanly onto `POST payments/` → `batches/<id>/confirm/` → `status/` → `payments/<id>/`. The
  stage checklist on `1620:15388` is what `status/` already returns; the reference number
  `SWP-20251212-4821` is `transaction_reference`. **[V from the design side]**
- **Payment failure recovery** — `1620:13563`'s three options (Retry now / Change payment method /
  Schedule for a future date) map exactly onto `POST payments/<id>/resolve/`'s `action`,
  `payment_method_id` and `scheduled_for`. **[V]**
- **AI Cash Context** on the payment screens is `POST ai/cash-context/`, near-verbatim. **[V]**
- **Projected balance** on Schedule Payment is `GET ai/balance-projection/`. **[V]**
- **Post-payment "Next up: Verizon $389 is due Dec 15"** is `bills/next-due/`. **[V]**
- **Phone sign-in** (`1617:9796`) is fully served by `auth/login/phone/request|verify/`. **[R]**
- **Account Type sheet** (Business/Individual) is supported — `AccountType.INDIVIDUAL` exists and
  registration branches on it. **[R]**
- **Registration returns tokens on OTP verify**, so mobile can go straight into onboarding without a
  second sign-in. **[R]**
- **Bank link, scan, candidate review, import** all exist and match the Plaid Role flow's structure.
- Business Address → `address`, POC → `poc_name`, phone → `phone_number` all already exist on
  register. **[R]**

---

## 6. Open questions

1. **Does "scan" mean QR, or photograph any bill?** Everything about the size of that work depends on
   the answer. (§1.3)
2. **Is push in scope for the mobile release?** If yes, it needs a device endpoint, an adapter, and a
   BRD §1.2 amendment. If no, the notification design needs to admit it's in-app only. (§1.2)
3. **Which processor?** The design names three. (§3)
4. **Is the Home balance card the funding-account balance, or was a wallet assumed?** (§1.4)
5. **Whose profile is Edit Profile?** `users/profile/` is account-scoped — a teammate editing it would
   edit the owner's record. Mobile draws it as personal identity. **[R]**
6. **Was the plan catalogue re-expanded on purpose,** or did the mobile design branch before the
   3-plan decision? (§1.6)

## 7. Suggested order

1. Answer Q1–Q4 — they gate the largest items.
2. Ship the three auth defects (§4). Independent of mobile, small, one of them is a 500.
3. Registration name fallback (§1.1) — unblocks the whole sign-up flow, ~an hour.
4. Tab counts (§2.2) and the profile fields (§2.3).
5. `payments/quote/` (§2.1).
6. Then the large decisions: push, uploads/OCR, tokenization, billing.

---

## 8. What was not covered

Be aware of these holes before treating this as complete:

- **Add Bill part 2** (`1620:13907`, `13259`, `14113`, `13737`, `13329`, `13408`, `13479`) — not read.
- **Add Bill — QR code Scan** — sampled only; largely duplicates Add Vendor — Scan.
- **Plaid Role** — 1 of 8 screens read closely.
- **Pay** — 5 of 7 screens read.
- **The cross-cutting platform sweep died mid-run.** I hand-checked its highest-value items —
  push **[V]**, uploads **[V]**, OCR **[V]**, JWT lifetimes **[V]** (access 15 min, refresh 30 days,
  rotating with blacklist-after-rotation, [base.py:132-138](config/settings/base.py#L132-L138)) — but
  **not**: offline/caching headers, ETag support, app-version/force-upgrade gating, deep-link
  sufficiency of notification metadata, cursor vs page pagination for infinite scroll, or whether a
  single global-search endpoint is needed for the Search screen (today it would fan out to 3+ calls).
- **Every [R] item is unverified.** The verification pass never ran.
