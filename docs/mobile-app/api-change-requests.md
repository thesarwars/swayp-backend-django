# API change requests

**For:** the Swayp backend team.
**From:** the mobile app team, after integrating the app with `https://swayp.jumatechs.xyz/api/v1` (October 2026).

This document lists what the mobile app needs from the API and what we found wrong or unclear while integrating it. Every item says which endpoint it is about, what happens today, what the app needs, which screen needs it, and what the app does in the meantime.

**Where the facts come from.** "Observed" means we sent the request to the development server on 2026-09-30. Those probes were unauthenticated or validation-only: we did not create accounts, codes, sessions or payments, so **no authenticated success body has been verified yet**. Everything else comes from the docs in `docs/integration docs/` and from the live OpenAPI schema (`/api/schema`, fetched the same day).

**Severity.**
- **blocker**: a feature cannot ship until this is answered.
- **major**: the app works around it, but the workaround is fragile, wrong for some users, or a security or money risk.
- **minor**: a missing field, a missing doc line, or a convenience.

Requests are grouped by area and ordered by severity inside each area. Ids (`AUTH-1`, `PAY-3`…) are stable, so you can refer to them in tickets.

## At a glance

| Blockers | Why |
| --- | --- |
| [VEND-1](#vend-1--blocker--no-way-to-obtain-an-ach-payee-token) | There is no documented way to get the `provider_token` that ACH payees need. In release builds the app can only add check-by-mail payees. |
| [BANK-1](#bank-1--blocker-unverified--can-an-account-with-no-subscription-link-a-bank) | New users link a bank straight after sign-up, before they have any plan. If the link endpoints refuse that, every new user is stuck on the first onboarding screen. Please confirm. |

The most important **major** items:
- **PAY-1:** an unconfirmed payment strands its bill.
- **API-2:** say which endpoints honour `Idempotency-Key`.
- **AUTH-1:** an invalid refresh token answers 500.
- **API-1:** the OpenAPI response schemas do not match what the server returns.
- **BANK-4:** the history window is 24 months in the designs and 12 on the server.

Contents:
1. [Auth](#auth)
2. [Banking & onboarding](#banking--onboarding)
3. [Dashboard & notifications](#dashboard--notifications)
4. [Bills](#bills)
5. [Payments](#payments)
6. [Vendors](#vendors)
7. [Billing](#billing)
8. [Cross-cutting / OpenAPI](#cross-cutting--openapi)
9. [Security hygiene](#security-hygiene)
10. [Contradictions to settle](#contradictions-to-settle)
11. [Not requested yet](#not-requested-yet)

---

## Auth

#### AUTH-1 · major · An invalid refresh token answers 500
- **Endpoint:** `POST /auth/refresh`, `POST /auth/logout`.
- **Today:** a malformed token (`"not.a.jwt"`) and a well-formed forged JWT both get **500** `{"success":false,"message":"Internal server error."}`. Observed, twice each.
- **Needed:** 401 from refresh for any token that is invalid, expired or revoked. 204 (or 401) from logout.
- **Screen:** every signed-in screen, because the client refreshes the access token automatically.
- **App today:** the client cannot tell "the session is gone" from "the server is down". It treats every refresh failure except 429, 502, 503, 504, offline and timeout as a dead session and signs the user out. So a real server fault on `/auth/refresh` signs users out.

#### AUTH-2 · major · OTP codes cannot be received on the development server
- **Endpoint:** `register`, `forgot-password`, `resend-otp`, `login/phone/request`.
- **Today:** codes are only written to the server log.
- **Needed:** real email on dev and staging, or a fixed code for named test accounts.
- **Screen:** sign-up, password reset, phone sign-in.
- **App today:** nothing the app can do. Nobody without server-log or database access can test these flows end to end on a phone.

#### AUTH-3 · major · Auth errors carry no machine-readable code
- **Endpoint:** every `/auth/*` error, in particular `login`, `verify-otp` and `resend-otp`.
- **Today:** errors carry English text only. The lockout is not a 429 with `Retry-After`.
- **Needed:** a `code` such as `ACCOUNT_NOT_VERIFIED`, `ACCOUNT_LOCKED`, `OTP_INVALID`, `OTP_EXPIRED` or `OTP_ALREADY_USED`. Lockouts should answer 429 with `Retry-After`.
- **Screen:** email sign-in, the OTP screen.
- **App today:** the app matches message text ("Account is not verified.", "…may have been used already"). For a 429 it reads `Retry-After`, then a count of seconds or minutes in the message, and otherwise locks "Send Again" for 60 s. Any rewording on the server breaks these branches. See also [API-3](#api-3--major--other-errors-the-app-can-only-recognise-by-their-english-text).

#### AUTH-4 · major · A reset code cannot be checked before the new-password step
- **✅ Fixed**: `POST /auth/verify-otp { email, otp, purpose: "RESET_PASSWORD" }` checks and uses up the code on the code screen. A right code answers with `data.reset_token` and `data.expires_in` (600 s), and nobody is signed in. `POST /auth/reset-password { email, reset_token, password }` sets the password. The token works for that email only and stops working once the password changes. A rejected password leaves it usable. Wrong, expired and over-limit codes are 400 with `errors.otp`; a bad token is 400 with `errors.reset_token`. Sending `{ email, otp, password }` straight to `reset-password` still works. See e2 §4.
- **Endpoint:** `POST /auth/verify-otp`, `POST /auth/reset-password`.
- **Today:** `verify-otp` accepts `purpose: "REGISTRATION"` only. The design is email → code → new password, so a wrong reset code is discovered only after the user has typed a new password twice. The error shape for a wrong or expired code is undocumented.
- **Needed:** either let `verify-otp` accept `RESET_PASSWORD` and return a short-lived reset token, or add a validate call that does not consume the code. Also document the wrong-code and expired-code errors.
- **Screen:** OTP screen, new password.
- **App today:** the code is kept in memory and sent with the new password. A 400 without `errors.password` sends the user back to the OTP screen.

#### AUTH-5 · major · Password rules are too weak and reject common special characters
- **Endpoint:** `register`, `reset-password`.
- **Today:** there is no minimum length (`Ab1@` is accepted). The special character must come from a fixed set of 20 (`! " # $ % & ( ) * , . : < > ? @ ^ { | }`), so `-`, `_`, `+`, `=`, `/`, `;`, `'`, `[`, `]`, `\`, `` ` ``, `~` and space fail. The message does not say which characters count. Observed, character by character.
- **Needed:** at least 8 characters, and accept any non-alphanumeric character.
- **Screen:** sign-up, new password.
- **App today:** the client enforces 8 characters and the server's 20-character set. iOS strong-password suggestions are not offered, because they use `-` and the server would refuse them.

#### AUTH-6 · major · Phone sign-in codes go by email, but the design says SMS
- **Endpoint:** `POST /auth/login/phone/request`, `resend-otp`.
- **Today:** the default `channel` is `EMAIL`, and `SMS` answers **501** "SMS delivery is not available in this release. Use EMAIL." (observed). No guide mentions `channel`.
- **Needed:** ship SMS, or confirm that email is intended so the copy can change. Document `channel`.
- **Screen:** phone sign-in, OTP screen, the OTP method sheet.
- **App today:** sends no `channel`, so the server uses its email default. The "Send OTP via SMS" option is disabled.

#### AUTH-7 · major (product / legal) · Registration consent and business fields have no place in the mobile design
- **Endpoint:** `POST /auth/register`.
- **Today:** `terms_accepted`, `signatory_confirmed`, `marketing_opt_in`, `industry` and `business_size` have no input in the mobile "Create Account" design. The object-level rules are undocumented: is a name required, is `business_name` required for `BUSINESS`, are the consent flags enforced?
- **Needed:** decide whether consent belongs in the mobile design, or whether mobile sign-ups may record none. Document the object-level rules.
- **Screen:** sign-up.
- **App today:** sends none of these fields. A business sign-up sends the point-of-contact name as both `full_name` and `poc_name`.

#### AUTH-8 · minor · Reset with an unknown email answers 500
- **✅ Fixed** (`79d387f`): 400 with `errors.otp: ["No reset code is pending. Request a new one."]`. This is the same answer as for a known email with no code, so it doesn't reveal whether the account exists. Wrong, expired and over-limit codes are also 400s with `errors.otp`. See e2 §4.
- **Endpoint:** `POST /auth/reset-password`.
- **Today:** **500** for an unknown email, also when the password is invalid too. Observed twice.
- **Needed:** a 400, or the same neutral answer as forgot-password (see [SEC-3](#sec-3--major--auth-endpoints-reveal-which-accounts-exist)).
- **Screen:** new password.
- **App today:** shows the generic server error.

#### AUTH-9 · minor · Sign-in takes an email only, but the design says "Email or User ID"
- **Endpoint:** `POST /auth/login`.
- **Today:** a non-email value gets `errors.email: ["Enter a valid email address."]`. Observed.
- **Needed:** support User ID sign-in, or confirm the design label is wrong.
- **Screen:** email sign-in.
- **App today:** the label stays "Email or User ID", and the field accepts email addresses only.

#### AUTH-10 · minor · A phone number cannot be added after registration
- **✅ Fixed** (`cb0ac5c`): `POST /users/profile/phone { phone_number }` emails a code to the account's address and returns the masked address in `data.email`. `POST /users/profile/phone/verify { phone_number, otp }` sets the number and returns the updated profile. The code only works for the number it was requested for. See e2 §5, "Adding or changing the phone number".
- **Endpoint:** the profile endpoints.
- **Today:** there is no way to add or change the phone number later.
- **Needed:** a way to set it, with verification.
- **Screen:** phone sign-in.
- **App today:** an account created without a phone number can never use phone sign-in.

#### AUTH-11 · minor · OTP lifetimes and limits are undocumented
- **✅ Fixed** (`79d387f`): codes live 5 minutes and die after 5 wrong guesses (400 `errors.otp: ["Too many incorrect attempts. Request a new code."]`). Resends are limited to one per 60 s and 5 per hour, per purpose. `resend-otp` returns the masked address in `data.email`. `login/phone/request` is throttled on the server, silently. See e2 §3, "Lifetimes and limits".
- **Endpoint:** `resend-otp`, `login/phone/request`, `verify-otp`.
- **Needed:**
  - Document the code lifetime and the attempt limit.
  - Confirm that `resend-otp` returns the masked address in `data.email`.
  - Confirm that `login/phone/request` is throttled on the server (its neutral answer hides any limit).
- **Screen:** OTP screen.
- **App today:** shows the server's masked email when it is present, and masks the address locally when it is not.

#### AUTH-12 · minor · `PATCH /users/profile` has no documented response body
- **✅ Fixed** (`da1454f`): `PATCH` returns the full updated profile in the standard envelope, the same body as `GET`, so no refetch is needed. OpenAPI now declares it. See e2 §5.
- **Endpoint:** `PATCH /users/profile`.
- **Today:** the guide documents the request ("partial — send only what changed", empty body = 400) but not what comes back: the updated profile, an envelope with a message, or nothing.
- **Needed:** one line saying what the success body is.
- **Screen:** Profile Settings → Edit Profile.
- **App today:** ignores the body and refetches `GET /users/profile`, which costs one extra request per save.

#### AUTH-13 · minor · No way to set the profile picture
- **Endpoint:** `GET /dashboard/profile-summary` returns `profile_picture`; nothing writes it.
- **Needed:** an upload endpoint (multipart) and a way to remove the picture, or confirmation that avatars are not a feature.
- **Screen:** Profile, Edit Profile ("Change Profile Picture").
- **App today:** the sheet opens and says pictures cannot be changed yet; the screens show `profile_picture` when the API has one and a placeholder otherwise.

---

## Banking & onboarding

#### BANK-1 · blocker (unverified) · Can an account with no subscription link a bank?
- **✅ Answered and fixed**: yes. `link/token` and `link/exchange` work with no subscription; checked with a fresh account on the mock provider (200, then 201). Before, nothing limited an account with no plan, so it could link any number of banks. Now it can link **one**, and a second link without a plan answers 402 *"Choose a plan to connect more than one bank."* Disconnecting frees the slot. See e5, "The bank limit is a plan limit".
- **Endpoint:** `POST /banking/link/token`, `POST /banking/link/exchange`.
- **Today:** the backend wizard order is business → plan → payment → bank. The mobile app shows the bank step only, right after the first sign-up, when no plan exists yet. If these endpoints answer 402 or 400 for an account without a subscription, every new user is stuck on the first onboarding screen. We could not verify this without creating an account.
- **Needed:** allow one connection without a subscription, or tell us the precondition. One call with a fresh account settles it.
- **Screen:** onboarding: connect bank, bank sign-in.
- **App today:** a 402 opens the app-wide "Upgrade your plan" prompt, and the onboarding screen stays where it is. The user can skip the bank step.

#### BANK-2 · major · Publish the onboarding response bodies
- **✅ Fixed**: OpenAPI now declares all four bodies: `OnboardingSummaryResponse`, `ImportResponse` (201), and `OnboardingStateResponse` for both `users/onboarding` and `skip-bank`. `skip-bank` answers with the updated progress. On the disagreement, the code always sends all four fields, so `banking-api-documentation.md` was right and `e5-banking.md` now matches: `connection.institution_logo` (`""` when there is none), `connection.connected_at`, `rail_readiness.check_ready` and `rail_readiness.needs_details`. A test fails if the schemas and the real responses ever disagree. See e5 §7.
- **Endpoint:** `GET /banking/onboarding-summary`, `POST /banking/scans/{id}/import`, `GET /users/onboarding`, `POST /users/onboarding/skip-bank`.
- **Today:** OpenAPI says "No response body" for all four. The two banking docs disagree on whether `rail_readiness.needs_details`, `rail_readiness.check_ready`, `connection.institution_logo` and `connection.connected_at` exist.
- **Needed:** response schemas, and a decision on those fields.
- **Screen:** onboarding: review bills, bills ready. The "N vendors need ACH details" row depends on `needs_details`.
- **App today:** reads the shapes from the docs' captured bodies and shows each readiness row only when its field is present.

#### BANK-3 · major (please verify) · Onboarding "payment" step when no money is collected
- **✅ Answered (no change needed)**: when `collects_money` is false, step 3 is **complete**, not just skippable, as soon as a plan exists. It is also complete during a trial. It can never be complete without a plan, though. An app that links the bank first gets the bank step complete and `current_step: 2` (plan) until a plan is chosen, so treating `current_step` as "the bank step" is wrong in that order. Whether mobile sign-ups must go through the plan step is a product decision. The rule for each step is now in e2 §6, "When each step counts as complete".
- **Endpoint:** `GET /users/onboarding`.
- **Today:** with the mock billing provider (`collects_money: false`), it is unclear whether step 3 ("payment") reports complete or skippable. If it does not, `current_step` can never reach the bank step.
- **Needed:** confirm that step 3 is complete or skippable when `collects_money` is false.
- **Screen:** onboarding: connect bank (the Skip pill is shown only when the bank step is skippable).
- **App today:** treats an unknown answer as skippable.

#### BANK-4 · major (product) · History window: the designs say 24 months, the server caps at 12
- **✅ Fixed**: the answer is **24**. The server has scanned 24 months since `0dcb29c` (2026-08-25): `months` accepts 1–24, defaults to 24, and the scan reports `months_history: 24`. The "1–12, 24 is a design bug" text in `banking-api-documentation.md` was out of date and has been corrected, along with the `12`s in the e5 examples. `POST /banking/link/token` now also returns `months_history`, so the pre-link copy can come from data. Note that the mock provider only has 12 months of transactions, so on dev a scan says 24 but finds 12 months of data. If the dev server still reports 12, it is running a build older than `0dcb29c`.
- **Endpoint:** `POST /banking/scans` (`months`), `TransactionScan.months_history`.
- **Today:**
  - The onboarding designs and the product owner say the scan reads **24 months** of history.
  - The server caps it at **12**: the banking doc says `months` is 1–12, larger values are clamped, and 24 is "a known design bug".
  - OpenAPI declares `maximum: 24`, and the e5 guide's intro still says "scan 24 months".
- **Needed:** one answer. If two years is the product promise, raise the cap to 24. Otherwise confirm 12, and we will ask design to change the copy. Also return the window from `link/token` (or another call made before the link), so the pre-link copy can come from data.
- **Screen:** onboarding: connect bank ("Returns 24 months of history"), verifying, scanning ("Plaid returned N months of history"), how it works, bills ready.
- **App today:** before the link, the copy says 24 (the design, as the product owner asked). After the link, every screen shows the scan's `months_history`, which is 12. So a user reads "24 months" on one screen and "12 months" two screens later.

#### BANK-5 · major (before production) · Link token for real Plaid
- **Endpoint:** `POST /banking/link/token`.
- **Today:** the endpoint takes no body and returns no `expiration` that the app can use for real Plaid.
- **Needed:** accept `android_package_name` and `redirect_uri` (the iOS OAuth redirect), and return `expiration`.
- **Screen:** connect bank, once the Plaid Link SDK is added.
- **App today:** only the mock provider is supported. The app sends `public-mock-<institution>`, never collects bank credentials, and shows "Bank linking isn't available in this version of the app yet" for any other provider.

#### BANK-6 · minor · No way to find a connection's latest scan
- **✅ Fixed**: every connection in `GET /banking/connections` and `GET /banking/connections/{id}` now carries `latest_scan: { id, status } | null`, and `onboarding-summary` has `detection.scan_id`, the newest scan overall. If the exchange answer is lost, read `latest_scan` from the connections list instead of starting a second scan. See e5 §6, "Getting back to a scan".
- **Endpoint:** new, for example `GET /banking/scans?connection_id=`, or `detection.scan_id` in the onboarding summary.
- **Today:** a user who links a bank and leaves can only get back to the detected bills by starting a new scan.
- **Screen:** onboarding resume, and a future in-app review.
- **App today:** a recovered link (an exchange whose answer was lost) and an exchange answered without `scan` both start a second scan.

#### BANK-7 · minor · Onboarding summary is missing two counts
- **✅ Fixed**: `onboarding-summary` now has `detection.months_history` (the window of the newest scan, `null` before any scan) and `bills.total_bills` (the same number `bills/summary` reports). Both are in the OpenAPI schema. See e5 §7.
- **Endpoint:** `GET /banking/onboarding-summary`.
- **Needed:** `detection.months_history` (for "From N mo history") and `bills.total_bills` (it already exists in `bills/summary`), for the "Bills (n)" chip.
- **Screen:** bills ready.
- **App today:** takes the months from the cached scan, or shows "From your bank history". Uses the imported count when `total_bills` is missing.

#### BANK-8 · minor · Detected bills cannot be edited before import
- **Endpoint:** new, for example `PATCH /banking/scans/{id}/candidates/{cid}` (amount, category, cadence, due day).
- **Today:** the design says "You can edit any detail", but there is no edit call.
- **Screen:** review bills.
- **App today:** candidates are imported as detected.

#### BANK-9 · minor · Failed scans
- **Endpoint:** `GET /banking/scans/{id}`.
- **Needed:** say whether `progress.is_complete` becomes true for a `FAILED` scan, and add a machine-readable failure `code` next to `error_message`.
- **Screen:** scanning.
- **App today:** stops polling on either `is_complete` or a final status, and shows `error_message` (or a fallback) with "Try Again".

#### BANK-10 · minor · Onboarding progress after skip and disconnect
- **Endpoint:** `GET /users/onboarding`, `POST /users/onboarding/skip-bank`.
- **Needed:** say whether the bank step goes back to incomplete after a disconnect (a sticky "was completed" flag would avoid re-prompting), and return the updated progress from `skip-bank`.
- **Screen:** onboarding gate.
- **App today:** calls `skip-bank` in the background (retried twice) and closes the flow at once. It ignores the answer, then refetches `users/onboarding`.

#### BANK-11 · minor · `provider` casing
- **Endpoint:** `LinkToken.provider` and `BankConnection.provider`.
- **Today:** `"mock"` in one, `"MOCK"` in the other.
- **Needed:** one casing.
- **App today:** compares without regard to case.

---

## Dashboard & notifications

#### DASH-1 · major · Notifications cannot be filtered on the server
- **✅ Fixed** (`bdb54ce`): `GET /notifications` takes `type` (repeatable), `category=transactions|promotion` and `isRead=true|false`. Filters apply before pagination, so `pagination.totalItems` counts only matching rows and an empty page means none match. Sending `type` and `category` together returns rows that match both. `transactions` covers PAYMENT, BILL_DUE, PAYMENT_FAILED, PAYMENT_REVERSED, AUTOPAY_EXECUTED, PAYMENT_ARRIVED and LATE_FEE_WARNING; SYSTEM and SECURITY appear under neither chip.
- **Endpoint:** `GET /notifications`.
- **Today:** only `page` and `pageSize` exist.
- **Needed:** `type` (repeatable), or `category=transactions|promotion`, and `isRead=false`.
- **Screen:** notifications (Transactions / Promotion chips).
- **App today:** filters on the client and loads up to 4 pages of 50 to fill a chip. An empty chip cannot be told apart from "the rows are on a later page".

#### DASH-2 · major (blocks push, which is deferred) · Device routes are mounted at the wrong path
- **Endpoint:** `POST /notificationsdevices/register/`, `/notificationsdevices/unregister/`.
- **Today:** the routes have no `/` after `notifications` and end with a trailing slash. The documented `/notifications/devices/register/` is a 404. Observed (401 on the broken path, 404 on the documented one).
- **Needed:** `/notifications/devices/register` and `/notifications/devices/unregister`, without a trailing slash, like every other route.
- **Screen:** none yet. Push is not integrated.

#### DASH-3 · major (before realtime is enabled) · WebSocket
- **Endpoint:** `wss://…/ws/notifications/?token=`.
- **Today:** the dev host has no WebSocket route (HTTP 404). The guide's URL uses `api.getswayp.com`. The access JWT travels in the query string; see [SEC-4](#sec-4--major--websocket-sends-the-access-token-in-the-url).
- **Needed:** the route on dev and staging, and a safer handshake.
- **Screen:** none yet. Realtime is not integrated.

#### DASH-4 · minor · Unread count
- **Endpoint:** `GET /notifications`, `GET /dashboard/home`.
- **Today:** the count exists only in `/dashboard/profile-summary`. `GET /notifications/unread-count` is a 404.
- **Needed:** `unreadCount` next to `pagination` in the list, and in `dashboard/home`.
- **Screen:** home bell, notifications.
- **App today:** the bell polls the profile summary every 60 s while home is focused. "Mark all read" shows when any loaded row is unread, so the badge and the list can disagree.

#### DASH-5 · minor · Mark-read answers
- **Endpoint:** `PATCH /notifications/{id}/read`, `PATCH /notifications/read-all`.
- **Needed:** return the updated row (`isRead`, `readAt`) and the new unread count. Document what re-reading a read notification returns, and the 404 rule.
- **App today:** updates the list optimistically, rolls back on error, handles a 404 quietly, then refetches the unread count.

#### DASH-6 · minor · Notification `metadata` is untyped
- **Endpoint:** `Notification` schema.
- **Today:**
  - `metadata` is a free-form object and `type` is a bare string.
  - The REST docs use `payment_id`, the push payload uses `paymentId`.
- **Needed:**
  - Publish the keys for each type (`bill_id`, `occurrence_id`, `payment_id`, `fee_charge_id`), guaranteed as uuid strings.
  - Reference `TypeEnum`.
  - Use one casing.
- **Screen:** notification deep links.
- **App today:** reads the snake_case keys and validates them as uuids. `payment_id` opens the payment detail. `bill_id` and `occurrence_id` open the Pay tab ([PAY-4](#pay-4--major--a-payment-or-occurrence-cannot-be-traced-back-to-its-bill-or-vendor)). Fee and security notifications do not navigate.

#### DASH-7 · minor · Notifications use offset paging on a feed that grows at the head
- **Endpoint:** `GET /notifications`.
- **Today:** a new notification shifts every page, so rows are duplicated or skipped between pages.
- **Needed:** a cursor (`before=<id or createdAt>`).
- **App today:** removes duplicates by id.

#### DASH-8 · minor · `vendors_preview` is missing the next due date, and `monthly_amount` is unclear
- **Endpoint:** `GET /dashboard/home` → `vendors_preview[]`.
- **Today:** no next due date. A captured body shows `monthly_amount: "0.00"` for a vendor billed $3,200 a month.
- **Needed:** `next_due` (date or null). Document what `monthly_amount` measures, and the order and limit of the list.
- **Screen:** home, My Providers cards.
- **App today:** the card's "Last Date:" line became "This month:" with `monthly_amount`.

#### DASH-9 · minor · Funding account on the home dashboard
- **Endpoint:** `GET /dashboard/home`.
- **Needed:** `funding_account: { id, name, mask, display } | null`. It already exists in `banking/onboarding-summary`.
- **Screen:** home, Details Confirmation card ("From").
- **App today:** the "From" row is static design content.

#### DASH-10 · minor · Document `recent_bills` and the pay panel
- **Endpoint:** `GET /dashboard/home`.
- **Needed:** the selection rule, order and limit of `recent_bills`, and the page size and order of `pay_panel.items`.
- **App today:** `pay_panel.items` holds only the server's active tab, so Payment Centre shows that tab's rows (up to 5, earliest due first).

#### DASH-11 · minor · Profile and greeting
- **Endpoint:** `GET /users/profile`, `GET /dashboard/profile-summary`.
- **Today:**
  - The profile has no `id` and no avatar.
  - `greeting` in the summary has an undocumented format and timezone.
- **Needed:** an `id` on the profile, and either documentation for `greeting` or its removal.
- **Screen:** home header.
- **App today:** the avatar comes from the summary's `profilePicture` (https only). The greeting is computed from the device clock.

#### DASH-12 · product decision · The design has a wallet, the API has none
- **Endpoint:** none (`GET /wallet` is a 404, and E6 §1.3 says there is no wallet by design).
- **Today:** the home balance card ($12,547.80), the "Balance" pill and "From My Wallet / Wallet Number" are design content with no data behind them. So are the wallet tab's Add Funds, Transfer Fund and deposit history.
- **Needed:** a product decision, not an endpoint. Either the labels change (for example "Due this month"), or product keeps a stored-value wallet, which would need a ledger the backend says it will not hold.
- **App today:** the product owner deferred the wallet. These parts stay as designed, with static values.

---

## Bills

#### BILLS-1 · major · Bill create and update have no schema, and the guides disagree on `frequency`
- **Endpoint:** `POST /bills/create`, `PATCH /bills/{id}/update`.
- **Today:**
  - OpenAPI has no request body and answers "200 No response body". The docs say 201 with a review summary.
  - e4 lists `WEEKLY · BIWEEKLY · MONTHLY · QUARTERLY · YEARLY`. The bills reference and `CadenceEnum` list `MONTHLY · QUARTERLY · WEEKLY · ONE_TIME`.
- **Needed:** publish the request and response schemas, with the `frequency`, `bill_type`, `autopay_mode` and `source` enums and the 201.
- **Screen:** the add-bill wizard (and edit, which is not built yet).
- **App today:** sends `vendor`, `category`, `payment_method`, `anchor_date` and `frequency` ∈ `MONTHLY | QUARTERLY | WEEKLY | ONE_TIME` (the four Figma chips) as documented in the bills reference. It accepts any 2xx.

#### BILLS-2 · major · QR decode returns names instead of ids
- **Endpoint:** `POST /bills/qr/decode`.
- **Today:**
  - The response has `vendor_name` and `category` as names.
  - There is no response schema.
  - The 422 body is `{ success, message }`, while the vendors twin answers `{ detail }`.
- **Needed:** `vendor_id` (the matched saved vendor, or null) and `category_id`, a response schema, and one 422 shape.
- **Screen:** QR scanner → add-bill wizard.
- **App today:** puts the vendor name in the vendor search box and matches the category by name. Scanned values are marked "Read from the QR code. Please confirm."

#### BILLS-3 · major · The server should write the autopay authorization text
- **Endpoint:** new, for example `POST /bills/autopay-authorization/preview` (vendor, amount, frequency, bill type, date, funding account).
- **Today:** the payments API returns its authorization text, but bill create expects the client to compose the NACHA sentence for `AUTO` bills.
- **Needed:** the exact `authorization_text` from the server, which the app then shows and sends back verbatim.
- **Screen:** add-bill review → "Authorize auto-pay" sheet.
- **App today:** composes the sentence on the client. It still needs legal review.

#### BILLS-4 · major · What happens to an autopay authorization after an edit?
- **Endpoint:** `PATCH /bills/{id}/update`.
- **Needed:** document whether a stored authorization stays valid when `amount`, `frequency`, `anchor_date` or `payment_method` of an `AUTO` bill changes, or whether fresh consent is required.
- **Screen:** edit bill (not built yet).

#### BILLS-5 · major · Bill detail is missing ids and uses numbers for money
- **Endpoint:** `GET /bills/{id}/details`.
- **Today:** no `vendor_id`, `category_id` or `payment_method_id`. Some money fields are numbers.
- **Needed:**
  - `vendor_id`, `category_id`, `payment_method_id` (plus the masked `account_ref`).
  - `next_occurrence_id` and its status.
  - `last_paid_at`.
  - Money as decimal strings, like the rest of the API.
- **Screen:** schedule a payment (uses `days_overdue`), and the bill detail and edit screens (not built yet).
- **App today:** the Pay tab prefetches bill detail, and the schedule screen reads `days_overdue` from it. No screen edits a bill yet.

#### BILLS-6 · major · No bill document upload
- **Endpoint:** new, for example `POST /bills/import/document` (photo or PDF → vendor, amount, due date, reference, with provenance).
- **Today:** there is no upload, OCR or import route under `bills`. `POST /bills/upload` and `POST /bills/import` are 404s (observed).
- **Screen:** Upload to Import (`(import-bill)/upload`, `details`).
- **App today:** these screens stay on demo data.

#### BILLS-7 · major (product + API) · The consumer utility flows have no backing
- **Endpoint:** none exists.
- **Today:** the electricity, capture and manual-bill flows need a meter or customer-account reference on a vendor or bill, biller-account validation, an amount-due lookup, and account-holder and phone fields. None exist, and there is no wallet to pay from.
- **Needed:** confirm that these flows are dropped, or specify the endpoints.
- **App today:** Home's "Enter Bill Details" opens the add-bill wizard and its bill-type badges open that category's bills, so these demo flows have no entry point any more.

#### BILLS-14 · major · Bill occurrences cannot be filtered by category
- **Endpoint:** `GET /bills/occurrences`, and the `BillOccurrenceRow` shape.
- **Today:**
  - The only filters are `status`, `vendor`, `date_from` and `date_to` (confirmed against `/api/schema` on 2026-10-08). There is no `category`, although `GET /vendors` already takes one as a uuid.
  - Rows carry `category_name`, a display name, and no `category_id`.
  - `GET /bills/summary` has counts per status but none per category.
- **Needed:**
  - `category` (category uuid) on `GET /bills/occurrences`, combinable with `status`. Repeatable would be better still.
  - `category_id` on every occurrence row, so a row can be tied to a category without comparing names.
  - Optionally a count per category (on `bills/summary`, or `bill_count` on each `bill-categories` row), so Home can label a badge "Electricity (3)" without reading the list.
- **Screen:** Home → "Bill Types" badges → a category's bills (`(home)/category-bills`).
- **App today:** pages through `GET /bills/occurrences` unfiltered and keeps the rows whose `category_name` matches, pulling up to 4 pages of 20 to fill one screen. Three things are wrong with that:
  - A category whose bills sit past the 4-page cap looks empty until the user scrolls, so the screen says "no bills in your first bills" instead of a plain count.
  - Every visit downloads up to 80 occurrences to show a handful.
  - Matching on the name breaks if a category is renamed or two categories share a name — the app has no id to fall back on. See also [BILLS-9](#bills-9--minor--category-codes).

#### BILLS-8 · minor · Occurrence rows
- **Endpoint:** `GET /bills/occurrences`, `GET /bills/summary`.
- **Needed:**
  - On each row: `payment_method` (or the default `rail`), `days_overdue`, and the `payment_id` of the active payment for `SCHEDULED` and `PAID` rows.
  - A multi-value `status` (or `unsettled=true`), with a documented order.
  - `scheduled_count` in the summary.
- **Screen:** Pay tab, schedule strip, a future bills list.
- **App today:** the Pay tab loads one list per pill (Overdue / Due / Upcoming). The schedule strip fetches bill detail to get `days_overdue`.

#### BILLS-9 · minor · Category codes
- **Endpoint:** `GET /bill-categories`.
- **Today:** no stable `code`. e1 documents `display_order`, but the API sends `displayOrder`.
- **Needed:** a stable `code`. `displayOrder` now decides which categories a user sees first, so please also confirm it is meant to be stable and unique.
- **Screen:** Home bill-type badges.
- **App today:** the badges are the first four categories by `displayOrder`. Which of the four drawings a badge gets is decided by keywords in the category's name ("electric", "power", "energy", "utilit" → the electricity badge, and so on); any other category gets a plain badge in its own `color`. A renamed category silently changes its artwork.

#### BILLS-10 · minor · No field for a scanned payment reference
- **Endpoint:** `POST /bills/create`.
- **Needed:** a field for the decoded `payment_ref`.
- **App today:** writes it into `notes` as "Ref …".

#### BILLS-11 · minor · Document the create rules
- **Endpoint:** `POST /bills/create`, `GET /vendors/{id}/payment-methods` (`schedule`).
- **Needed:**
  - The default when `payment_method` is omitted.
  - Whether create checks the lead time, and whether a past `anchor_date` is accepted.
  - The maximum amount and `notes` length.
  - Whether `AUTO` needs a connected funding account, and how that error reads.
  - A per-method `earliest_due_date` would let the app say "pick the 5th or later".
- **Screen:** bill schedule, bill method.
- **App today:** the earliest date is today in US Eastern time. A method that cannot meet the due date is greyed out, based on the `schedule` the payment-methods call returns.

#### BILLS-12 · minor · Please confirm
- Is `source: "QR"` accepted on create? (`SourceEnum` in OpenAPI is the vendor one.) The app sends it for scanned bills only.
- Does `GET /bills/next-due` answer 200 with `data: null` when nothing is outstanding? The success screen hides "Next up" then.
- Does `GET /bills/occurrences/upcoming` include overdue rows? The two docs disagree.

#### BILLS-13 · minor · Screens not built yet
These matter once the bill detail screens are built:
- `GET /bills/{id}/invoice`: invoice number and date, vendor address, bill-to block, line description and tax. Or confirm the invoice screen should drop them.
- `GET /bills/{id}/payments`: a `status` filter, counts per status, and the masked account of the method used.
- `GET /providers`: a catalogue row cannot become a vendor. There is no `network_payee_ref`, no detail route, and the NETWORK vendor contract is unclear ([VEND-6](#vend-6--major--directory-search-and-network-vendors-are-undefined)).

---

## Payments

#### PAY-1 · major · An unconfirmed payment strands its bill
- **Endpoint:** `POST /payments`, `POST /payments/{id}/confirm`, `POST /payments/{id}/cancel`, `GET /payments/{id}`.
- **Today:** create reserves a payment and turns the bill occurrence `SCHEDULED` before the user has authorized anything. If the app dies between create and "Confirm & Send", the bill looks scheduled and is never paid.
- **Needed:**
  - Auto-void payments that are not confirmed within N minutes, or mark the occurrence `SCHEDULED` at confirm instead of at create.
  - Allow cancelling an unconfirmed payment after its deadline.
  - Expose `authorized_at` and `authorization_text` on `GET /payments/{id}`, so an interrupted flow can resume.
- **Please confirm:**
  - The `AUTHORIZED` stage becomes `DONE` only at confirm. The app's clean-up depends on this.
  - `POST /payments` with one occurrence id always returns `batch_id: null` and exactly one payment.
- **Screen:** the whole pay flow (summary, schedule, confirm).
- **App today:**
  - After create, the app stores the payment id on the device (a "pending payment" marker in the keychain).
  - On the next Pay tab visit, and before every new create, it cancels that payment if it is still `PENDING`/`SCHEDULED` and not authorized.
  - Leaving Summary also cancels the reservation.
  - The marker holds one id, so a rare sequence can still leave a payment reserved. Only this change fixes it properly.

#### PAY-2 · major · Publish the payments reference
- **Endpoint:** `GET /payments/{id}/status`, `GET /payments/batches/{id}/status`, `GET /payments/{id}/failure`, `POST …/confirm`, `POST …/cancel`, `POST …/resolve`, and the `receipt`, `failure` and `progress` blocks of `PaymentDetail` (typed `string` in OpenAPI).
- **Today:** the guide links a "Payments API" document that is not in the repo. None of these bodies are documented, and the envelope of the payments family is unstated.
- **Needed:** the reference with captured bodies, and OpenAPI response schemas.
- **Screen:** processing, failed / resolve, payment detail.
- **App today:**
  - Types these bodies as unknown and reads them defensively.
  - The failure reason comes from the failed stage's detail. `GET /payments/{id}/failure` is not used.
  - Polls `GET /payments/{id}`, not `/status`.

#### PAY-3 · major · Payment history rows lack the vendor
- **Endpoint:** `GET /payments/history`.
- **Today:** rows have `providerName` (documented as nullable) and no vendor fields. Rows are camelCase while every other payment body is snake_case.
- **Needed:**
  - `vendor_id`, `vendor_name`, `bill_id` and `occurrence_id`.
  - `rail`, `estimated_arrival`, `scheduled_for` and `replaced_payment_id`.
  - Confirm whether `providerName` carries the vendor for bill payments.
- **Screen:** payment history.
- **App today:** "Recipient:" shows `providerName`, or a dash when it is null.

#### PAY-4 · major · A payment or occurrence cannot be traced back to its bill or vendor
- **Endpoint:** `GET /payments/{id}`, and a new `GET /bills/occurrences/{occurrence_id}`.
- **Needed:** the occurrence route, and `vendor_id`, `bill_id`, `funding_account_id` and `payment_method_id` on `PaymentDetail`.
- **Screen:**
  - Failed → "Choose payment method".
  - Notification deep links that carry an `occurrence_id` or `bill_id`.
  - Payment detail → bill.
- **App today:** those notifications open the Pay tab. "Choose payment method" shows "Changing the payment method is not available yet."

#### PAY-5 · major · Rail choice
- **Endpoint:** `POST /payments`.
- **Needed:**
  - Say what `rail` defaults to when omitted: the bill's saved method, or always `ACH_STANDARD`?
  - Allow a rail per occurrence in a batch.
  - Return the offer before create (`available_rails[{ rail, fee, estimated_arrival, available }]`, or a quote endpoint), so the client can show fees and hide same-day after the cutoff without computing Eastern time.
- **Screen:** summary, schedule.
- **App today:** omits `rail` when the bill has no saved method type, and shows the fee only after create.

#### PAY-6 · minor · Failure and resolve bodies
- **Endpoint:** `GET /payments/{id}/failure`, `POST /payments/{id}/resolve`.
- **Needed:**
  - A failure body with a display-ready `title` and `explanation`, `due_date`, `days_overdue`, a late-fee block and `available_actions`.
  - A resolve response that is the new payment (with `replaced_payment_id`), plus `authorization_text` when new consent is required.
  - e6 shows `action: "RETRY"`, while OpenAPI declares `retry | change_method | reschedule`. Which casing is right?
- **Screen:** failed.
- **App today:** sends lowercase actions. It reads the resolve body on a best-effort basis and compares the returned id with the failed one. With a new authorization text it opens Confirm, otherwise Processing.

#### PAY-7 · minor · Reschedule in place
- **Endpoint:** `POST /payments` + `cancel`, or a new `PATCH` of `scheduled_for`.
- **Needed:** reschedule an unconfirmed payment without cancel + create. Say whether non-business days are accepted for `scheduled_for`.
- **Screen:** schedule.
- **App today:** cancels the pay-now payment and creates a scheduled one.

#### PAY-8 · minor · Receipt file
- **Needed:** a receipt (PDF) for a settled payment.
- **Screen:** payment detail → "Download Receipts".
- **App today:** shares a plain-text receipt built from the payment detail.

#### PAY-9 · minor · Test hooks on the mock processor
- **Needed:** a documented way to force `FAILED` and slow stages on the mock processor.
- **Screen:** processing, failed (QA).

---

## Vendors

#### VEND-1 · blocker · No way to obtain an ACH payee token
- **Endpoint:** `POST /vendors` and `POST /vendors/{id}/payment-methods`, ACH branch.
- **Today:**
  - Both require `provider` + `provider_token` and refuse raw account numbers, but nothing documents how a client gets a token.
  - There is no tokenization endpoint, no processor SDK flow or client credential, and no list of valid `provider` values (the docs say `MOOV`, the designs say Dwolla).
  - There is no mock-token convention for the dev server. Bank linking has `public-mock-chase`; vendors have nothing.
- **Needed:** a server-mediated tokenization endpoint, or the documented client flow, plus the dev mock values.
- **Screen:** add a payee → bank details; "add payment details" for vendors imported without a method.
- **App today:**
  - In release builds ACH payees cannot be added: the app offers check by mail, and the ACH option explains that it is not available yet.
  - Development builds use a local mock token (`pm_mock_<uuid>`, provider `MOOV`). We do not know whether the dev API accepts it.
  - Raw bank numbers never leave the device.

#### VEND-2 · major · Adding a payment method returns the wrong shape
- **Endpoint:** `POST /vendors/{id}/payment-methods`.
- **Today:** per the schema, the 201 body has no `id` and no `account_ref`, and it echoes `provider_token`. The new method is not made primary even when the vendor has no primary.
- **Needed:**
  - Return the read shape (`VendorPaymentMethod`) and never echo the token.
  - Auto-promote a vendor's first method, or honour `is_primary`.
- **Screen:** linked details → add payment details.
- **App today:** refetches the vendor, finds the new method and calls `set-primary`.

#### VEND-3 · major · Vendor create may not return the vendor
- **Endpoint:** `POST /vendors`.
- **Today:** the schema says the 201 body echoes the request with no `id`. The guide shows the full vendor.
- **Needed:** the full vendor with `id` and `payment_methods[0].account_ref`. Please fix whichever source is wrong.
- **Screen:** add a payee → "Vendor saved".
- **App today:** without an `id` there is no success screen: the app shows a "Vendor saved" toast and closes the wizard.

#### VEND-4 · major · Vendors have no contact fields
- **Endpoint:** `GET /vendors/{id}`, `PATCH /vendors/{id}`.
- **Today:** the detail design has Contact Person, Phone Number and Email Address, but the API has no such fields.
- **Needed:** `contact_name`, `contact_phone` and `contact_email` (read + PATCH), or confirmation that the design drops them.
- **Screen:** linked details.
- **App today:** three of the six fields show "Not available".

#### VEND-5 · major · No vendor activity feed
- **Endpoint:** new, for example `GET /vendors/activity?page=`.
- **Today:** there is no feed of vendor events (linked, updated, removed, with timestamp and vendor name), and list rows have no `created_at` or `updated_at`.
- **Screen:** recent activities.
- **App today:** this screen stays on demo data.

#### VEND-6 · major · Directory search and NETWORK vendors are undefined
- **Endpoint:** `GET /vendors/directory-search`, `POST /vendors` NETWORK branch.
- **Today:**
  - The item shape differs between the vendors doc (`id, provider_name, provider_code, category, logo, supports_auto_pay`) and the schema (`external_id, name, category, verified, speed, network`).
  - The NETWORK branch needs `network_payee_ref` in one doc and `provider` + `provider_token` in the other.
  - Nothing says which field of a directory hit goes where.
  - A hit's `category` is a name, while create needs a uuid.
  - `q` is not in the schema.
- **Needed:** one contract for searching the directory and creating a NETWORK vendor from a hit.
- **Screen:** the add-vendor directory and QR paths (not built).

#### VEND-7 · minor · Vendor category is required, but the design has no category step
- **Endpoint:** `POST /vendors`.
- **Needed:** make `category` optional with a server default, or confirm that the app's added picker is the intended design.
- **App today:** "Add Manually" has an added Category field that is required before Continue.

#### VEND-8 · minor · Vendor list rows
- **Endpoint:** `GET /vendors`.
- **Today:** the card design shows "Assigned Bill Payer". No such field exists, and rows also lack `status` and a category name.
- **App today:** the card shows the payment method instead, and an "Active" pill.

#### VEND-9 · minor · Vendor update and detail bodies
- **Endpoint:** `PATCH /vendors/{id}`, `GET /vendors/{id}`.
- **Today:**
  - PATCH returns three fields (`name, category, notes`), not the vendor.
  - `total_paid` is sometimes a number.
  - `bills[]` items are undocumented.
  - The method read shape lacks `account_type` and `network_payee_ref`.
- **App today:** after PATCH it uses the values it sent, coerces `total_paid`, and never reads `bills`.

#### VEND-10 · minor · Error bodies for QR decode and routing validation
- **Endpoint:** `POST /vendors/qr/decode`, `POST /banking/routing/validate`.
- **Today:** the QR 422 body is `{ detail }` instead of the standard envelope. For routing validation, the status and body for a masked or malformed number, and the 429 body and `Retry-After`, are undocumented.
- **Screen:** add a payee → bank details.
- **App today:** treats a 400 as "Routing number invalid", a 429 as a rate-limit message, and anything else as "unavailable".

#### VEND-11 · minor · Delete semantics
- **Endpoint:** `DELETE /vendors/{id}`.
- **Needed:**
  - A restore endpoint (for "undo").
  - Document what happens to the vendor's unpaid occurrences and autopay.
  - Document whether delete is refused while a payment is in flight (bank disconnect is).
- **Screen:** linked providers, linked details.
- **App today:** confirms first ("Its bills and payment history are kept."), removes the card optimistically and rolls back on error.

---

## Billing

#### BILLING-1 · major · No way to read or replace the card on file
- **Endpoint:** new: `GET /billing/payment-method` → `{ brand, last4, exp_month, exp_year } | null` (or the same on `Subscription`), and `POST /billing/payment-method { payment_method_id }`.
- **Today:** nothing returns the card on file. `PATCH /billing/subscription` takes only `{ plan }`, so a trialing or past-due customer cannot add a card.
- **Screen:** subscriptions → payment ("Payment Method").
- **App today:** always shows "No card on file".

#### BILLING-2 · major · No invoice history
- **Endpoint:** new: `GET /billing/invoices?page=&pageSize=` with `{ id, period_start, period_end, total, status, paid_at, pdf_url }`.
- **Today:** only the current-cycle preview exists.
- **Screen:** subscriptions → payment ("Billing History").
- **App today:** shows the current-cycle invoice plus billed fees.

#### BILLING-3 · major · Reading `collects_money` creates a SetupIntent
- **Endpoint:** `POST /billing/payment-method/setup`; new, for example `GET /billing/config`.
- **Today:** the only way to learn whether the provider takes real money (and the publishable key) is the setup call, which creates a SetupIntent every time.
- **Needed:** a call with no side effects.
- **Screen:** subscriptions checkout.
- **App today:** calls setup on every checkout press. When money is collected, only a trial plan can be started in the app: card entry needs the Stripe SDK, which is deferred. Other plans show "Card payment isn't available in the app yet".

#### BILLING-4 · major · Plan eligibility per account
- **Endpoint:** `GET /billing/plans`.
- **Today:** `trial_days` and `price_locked` are properties of the plan. The app cannot tell a returning customer, or customer number 501, that the offer no longer applies.
- **Needed:** `trial_eligible` and `lock_available` (or `founding_spots_remaining`) per account.
- **Screen:** choose plan (badge), payment (CTA).

#### BILLING-5 · major · Cancellation semantics
- **Endpoint:** `DELETE /billing/subscription`.
- **Needed:** document whether access ends immediately and whether anything is refunded. Return `ends_at`. Cancel at period end is preferred.
- **Screen:** subscriptions → cancel confirmation.
- **App today:** treats any 2xx as cancelled.

#### BILLING-6 · major · `PAST_DUE` and `provider_status` are undocumented
- **Endpoint:** `GET /billing/subscription`.
- **Needed:** when these occur (mock and Stripe), whether `GET subscription` still returns the row, whether allowances still apply, and how the customer recovers (depends on BILLING-1).
- **Screen:** subscriptions index banner.
- **App today:** shows a past-due banner.

#### BILLING-7 · major · Plan change when usage exceeds the target plan
- **Endpoint:** `PATCH /billing/subscription`.
- **Needed:** define the status code and a displayable message for a downgrade below current usage (seats, banks), and for a change with no subscription.
- **Screen:** manage plan.
- **App today:** warns before a downgrade with its own copy, then shows the server's message.

#### BILLING-8 · minor · Plan display content
- **Endpoint:** `GET /billing/plans`.
- **Needed:** `description`, `features: string[]`, and `billing_interval` if annual billing is ever planned. The design has a feature list and a "/year" plan.
- **App today:** builds the feature lines from the plan's allowances.

#### BILLING-9 · minor · Fees list
- **Endpoint:** `GET /billing/fees`.
- **Needed:** pagination, filters (`state`, date range), and `payment_id` on each row to link to the receipt.

#### BILLING-10 · minor · Invoice lines
- **Endpoint:** `GET /billing/invoice`.
- **Needed:** a machine-readable `state`, `fee_charge_id`, `payment_reference` and `created_at` on lines, and a `next_charge_date` on the preview. `period_end` is documented as "when the allowance resets", not "when the card is billed".
- **App today:** infers "refunded" from `total == 0`.

#### BILLING-11 · minor · Codes on 402 and 403
- **Endpoint:** every gated endpoint.
- **Needed:** for example `{ code: "plan_limit", limit: "BANKS" }`, so the app can preselect the plan that lifts the limit.
- **App today:** every 402 opens one app-wide "Upgrade your plan" prompt with the server's message, which leads to the plan list. A 403 is shown as an error.

---

## Cross-cutting / OpenAPI

#### API-1 · major · OpenAPI response schemas do not match the server
The schema is reliable for paths, request bodies and enums, but often wrong for response envelopes and computed fields. The app reads every envelope it has seen, so nothing breaks today. But a generated client is impossible, and every new field is a guess.

| Area | What to fix |
| --- | --- |
| Envelope | Model `{ success, message, data }` for auth, users, banking, billing, dashboard and notifications. The README lists "auth, bills, banking, billing, teams, users, categories" and omits dashboard and notifications. State which envelope payments use. |
| Pagination | `NotificationListResponse` and `PaymentHistoryResponse` have no `pagination`. `PaginationResponse` lacks `hasNext` / `hasPrevious`. `PaginatedVendorListList` and `PaginatedVendorPaymentMethodList` declare DRF's `count/next/previous/results`, while the server sends `items/pagination`. `bills/occurrences`, `bills/{id}/payments` and `payments/history` declare neither `page/pageSize` nor `pagination`. |
| Auth | No response schemas for `auth/*` or `users/onboarding*`. `Profile.phone_number` should be nullable. The register example is the legacy payload. Is `users/profile` enveloped? |
| Banking | `TransactionScan.progress` is an object `{ is_complete, thin_history }`, not a string. `link/exchange` omits `scan`. `category_guess_name` should be nullable. `months` maximum (BANK-4). `POST /banking/accounts` has no request body and declares an array. `GET /banking/connections/{id}` carries the DELETE's summary. Fields that are always present are not marked required. |
| Dashboard | `BillOccurrenceRow.status`, `.autopay_mode`, `PayPanel.active_tab` and `HomeVendorPreview.rail` are bare strings: declare the enums. |
| Bills | Create, update and QR decode have no schemas (BILLS-1, BILLS-2). `DELETE /bills/{id}/details`: the doc says 200 with a body, OpenAPI says 204. |
| Payments | `POST /payments` should be 201. `PaymentDetail.receipt/failure/progress` are typed `string` (PAY-2). `CurrencyEnum` is `BDT, USD, EUR`, while the guides say USD only. |
| Vendors | List, summary and directory query params are undeclared (`search, category, rail, status, q`). `summary`, `qr/decode` and `set-primary` have no response schema. Computed fields (`payment_rail, recurring_amount, amount_period, next_due, total_paid, monthly_spend, next_bill, bills, schedule`) are typed `string` with no nullability. `routing/validate` omits the envelope. |
| Billing | Model the envelope. Add request bodies for POST/PATCH subscription and POST addons. `POST subscription` should be 201. `is_trialing` should be boolean and `trial_days_remaining` integer or null. `GET subscription` should be nullable. Add the allowances schema. POST addons returns one object or null. Declare 400/403/503. |

#### API-2 · major · Say which endpoints honour `Idempotency-Key`
- **Today:** E1 says endpoints that create money-moving work accept the header, and gives `POST /payments` as the example. Only `banking/scans/{id}/import` says so explicitly in its own doc.
- **Needed:** list every endpoint that honours it, and add it where it is missing. These are the ones that matter:

| Endpoint | Risk without it | What the app does |
| --- | --- | --- |
| `POST /banking/link/exchange` | A retry after a timeout creates a second connection, or a false 402 on Founding. | Sends a key. Records the existing connection ids before the exchange and treats a new ACTIVE one as the lost answer. This costs one extra `GET /banking/connections` and does not survive a screen remount. |
| `POST /bills/create` | A second bill, and with auto-pay a second debit authorization. | Sends a key. Blocks double taps and keeps the button disabled after success. |
| `POST /vendors`, `POST /vendors/{id}/payment-methods` | A duplicate payee. | Sends a key and blocks double taps. |
| `POST /billing/subscription` | A second subscription. | Sends a key. |
| `POST /payments`, `…/confirm`, `…/resolve` | A second payment or a double confirm. | Sends a key: one per user intent, reused only when the same request is retried after an unknown outcome. |

#### API-3 · major · Other errors the app can only recognise by their English text
- **Today:**
  - `POST /payments` answers 400 "No funding account is available. Connect a bank account first."
  - 402 and 403 bodies have no code (BILLING-11).
  - Failed scans have no code (BANK-9).
  - Auth has none either (AUTH-3).
- **Needed:** a stable `code` on every error the app must branch on, for example `no_funding_account`.
- **App today:** matches `/no funding account/i` and then shows a "Connect a bank account" prompt instead of a toast. A rewording silently turns that prompt into a plain error toast.

#### API-4 · minor · Error bodies are not uniform
- **Today:**
  - Some `errors` values are plain strings instead of string arrays: `errors.subscription`, `errors.plan` (addons), `errors.payment_method_id`, `errors.consent_accepted`, and `errors.connection` on bank disconnect.
  - The declined-card sample has no `success` or `message`.
  - QR decode answers `{ detail }`.
  - Unknown routes and nginx-level errors answer HTML, not the JSON envelope (see SEC-1).
- **Needed:** `{ success: false, message, errors?: { field: string[] } }` everywhere, JSON for every 404, and 404 rather than 400 "not found" for another account's id (the banking doc says 400, E1 says 404).
- **App today:** accepts strings and arrays, reads `detail` and `message`, and flattens nested fields with dots (`payment_method.routing_number`).

#### API-5 · minor · One casing
- **Today:** `dashboard/home`, bills, vendors and payment bodies are snake_case. `dashboard/profile-summary`, `notifications` and `payments/history` are camelCase.
- **Needed:** pick one.

#### API-6 · minor · Trailing slashes in the docs
- **Today:** the integration guide's endpoint index (§9) and several domain docs write paths with a trailing slash (`login/phone/request/`, `resend-otp/`, `connections/<id>/`, `scans/<id>/import/`, `GET vendors/?search=`…). The server answers 404 with an HTML page for any trailing slash. Observed on several routes.
- **Needed:** fix the docs, or accept both forms.
- **App today:** never sends a trailing slash.

---

## Security hygiene

#### SEC-1 · major · Django `DEBUG` is on
- **Today:** an unknown URL returns Django's technical 404 page, which lists every URL pattern of the API. Observed on the development host.
- **Needed:** `DEBUG=False` everywhere outside a developer's machine (and certainly in production), and JSON 404s in the standard error shape.

#### SEC-2 · major · No HSTS
- **Today:** `http://` redirects (301) to `https://`, but responses carry no `Strict-Transport-Security` header. Observed.
- **Needed:** HSTS on the API host.
- **App today:** release builds refuse any API URL that is not `https://`.

#### SEC-3 · major · Auth endpoints reveal which accounts exist
- **Endpoint:** `verify-otp`, `resend-otp`, `forgot-password` ("User does not exist."), `register` ("Phone number already exists.").
- **Today:** phone sign-in is deliberately neutral ("If that number is registered, a code has been sent."), but these endpoints are not. Observed.
- **Needed:** neutral answers, at least for forgot-password and resend-otp.
- **App today:** shows server messages as they are. It never invents its own "no account found" text.

#### SEC-4 · major · WebSocket sends the access token in the URL
- **Endpoint:** `wss://…/ws/notifications/?token=`.
- **Today:** the JWT in the query string ends up in proxy and server logs.
- **Needed:** accept an `Authorization` header on the handshake (React Native can send one), or issue a short-lived single-use ticket.

#### SEC-5 · minor · Session questions
- Is the email compared case-insensitively at sign-in and registration?
- Does a password reset revoke existing refresh tokens? (It should.)
- `POST /vendors/{id}/payment-methods` echoes `provider_token` in its response (VEND-2). Please stop echoing it.

---

## Contradictions to settle

Places where two docs, or a doc and the OpenAPI schema, disagree. The app follows the column "App follows" until you tell us otherwise.

| Topic | Disagreement | App follows |
| --- | --- | --- |
| `confirm_password` on register and reset | Sent in `frontend-integration-guide.md` §2.1 and `accounts-api-documentation.md`. Absent from OpenAPI; the server ignores it. | Not sent. |
| Register rules | `accounts-api-documentation.md`: 12-character minimum and many required fields. OpenAPI: only `email`, `password` required. The server has no minimum (AUTH-5). | The server. |
| Login | Guide §2.2 still says login sends a code and returns no tokens. e2 and OpenAPI: login returns tokens. | One-step login. |
| SMS | Guide §2.4: SMS is "rejected". README, e2 and the server: 501. | 501. |
| Refresh | `accounts-api-documentation.md` §6: the same refresh token comes back. Guide and e2: it rotates. | Stores whatever comes back (rotation). |
| `users/profile` envelope | e2: bare object. README: enveloped. OpenAPI: bare `Profile`. | Reads both. |
| Bill `frequency` | e4: `WEEKLY, BIWEEKLY, MONTHLY, QUARTERLY, YEARLY`. Bills reference and `CadenceEnum`: `MONTHLY, QUARTERLY, WEEKLY, ONE_TIME`. | The 4-value set. |
| Bill create / update responses | Docs: 201 with a review object. OpenAPI: 200, no body. | Any 2xx. |
| `GET /bills/occurrences/upcoming` | Bills reference: "due today or later". e4: "not a date filter". | Not used. |
| Scan `months` | Banking doc: 1–12, clamped. OpenAPI: max 24. e5 intro: 24 months. | BANK-4. |
| Scan polling | Banking doc: poll until `status != RUNNING`. e5: poll on `progress.is_complete`. | Stops on either. |
| Import request | Banking doc: `{ "all": true }`. e5: `candidate_ids` only. OpenAPI: both optional. | `candidate_ids`. |
| `onboarding-summary` fields | `banking-api-documentation.md` has `rail_readiness.check_ready/needs_details` and `connection.institution_logo/connected_at`. `e5-banking.md` does not. | Shows each when present (BANK-2). |
| Foreign ids | Banking doc §8: 400 "not found". E1 §5 and the guide: 404. | Both are errors; 404 is "not found". |
| Vendor list params and envelope | Docs: `search, category, rail, status` + `items/pagination`. OpenAPI: `page, pageSize` + DRF pagination. | Docs. |
| Vendor `status` filter | e3: `ACTIVE` or `DELETED`. Vendors doc: also `INACTIVE`. | Not sent. |
| Do imported vendors have payment methods? | e3: "imports them with methods attached". Banking doc: "arrive with no payment method". | May have none. |
| `bill-categories` field | e1: `display_order`. API: `displayOrder`. | `displayOrder`. |
| Notification row | E8 §4: `read_at`. OpenAPI: camelCase `isRead`, `createdAt`, `readAt`. | OpenAPI. |
| Notification metadata | REST guide: `payment_id`. Push payload: `paymentId`. | snake_case. |
| Device routes | Realtime guide: `/notifications/devices/register/`. OpenAPI and server: `/notificationsdevices/register/`. | Not used (DASH-2). |
| Notification preferences | E8 §4: bare `{ channels, preferences }` with `channels` as an object. OpenAPI: enveloped, `channels` as an array. | Not used yet. |
| Pay panel tab | E8 §1: `?tab=` on `dashboard/home`. OpenAPI: switch with `bills/occurrences?status=`. | The Pay tab uses `bills/occurrences?status=`. |
| `resolve.action` | e6: `"RETRY"`. OpenAPI: `retry, change_method, reschedule`. | Lowercase. |
| `GET /payments/history` params | e6: `status, providerId, categoryId, page`. OpenAPI adds `search, fromDate, toDate, pageSize`. | OpenAPI. |
| Staff `PATCH` payment routes | e6: 403 for customers. OpenAPI: 200/400/401/404, deprecated. | Not used. |
| Billing envelope | Docs: `{ success, message, data }`. OpenAPI: bare payloads. | Reads both. |
| Billing older vs newer doc | `billing-api-documentation.md` lacks `trial_days`, `provider_status`, `client_secret`, `trial_end`, `is_trialing`, `trial_days_remaining` and the `payment-method/setup` route. | e9 + OpenAPI. |
| `billing/fees` | e9: bare array. Billing reference: enveloped. | Reads both. |
| AI advisor consent | E7: nothing works without consent, and `is_live` means "a real LLM is wired". OpenAPI: the figures are deterministic, only the wording needs consent, and `is_live` means consent is in force. | Not integrated. |
| WebSocket host | Guide: `wss://api.getswayp.com/ws/notifications/`. The dev host has no such route. | Not integrated. |

---

## Not requested yet

These features are deferred on the app side, so their API questions are on hold: the wallet tab (balances, funding account choice, disconnect, connections in `ERROR`), the AI advisor, teams, reports and 1099, notification preferences, and push. The planning notes for them live with the mobile team. Ask us if you want them now.
