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
- **✅ Fixed (server side)**: `POST /banking/link/token` takes an optional `platform` (`ios`, `android`, `web`). For Android it sends Plaid the package name from `PLAID_ANDROID_PACKAGE_NAME`; for iOS and web, the redirect URI from `PLAID_REDIRECT_URI`. Plaid only accepts values registered in its dashboard, so the app sends `platform`, not the values themselves. `expiration` was already returned from real Plaid; it is `null` only on the mock. **Still needed before OAuth banks work on a phone:** both values set on the server and registered in the Plaid dashboard. See e5 §2.
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
- **✅ Fixed**: `PATCH /banking/scans/{id}/candidates/{cid}` takes any of `amount`, `category` (uuid), `cadence` and `due_day`, and answers with the updated candidate. Import builds the bill from these fields, so the edit carries through. `due_day` is checked against the cadence (1–7 for `WEEKLY`). An already-imported candidate is a 400. The vendor name is not editable here. See e5 §4, "Editing a candidate".
- **Endpoint:** new, for example `PATCH /banking/scans/{id}/candidates/{cid}` (amount, category, cadence, due day).
- **Today:** the design says "You can edit any detail", but there is no edit call.
- **Screen:** review bills.
- **App today:** candidates are imported as detected.

#### BANK-9 · minor · Failed scans
- **✅ Fixed**: `progress.is_complete` **is** `true` for a `FAILED` scan; it means "stop polling". Scans now carry `error_code`: `REAUTH_REQUIRED` (sign in to the bank again; the connection is `ERROR`), `HISTORY_NOT_READY` (try again later), `SCAN_FAILED` (anything else), or `""` when not failed. `error_message` is now always text written for the user. Before, an unexpected failure showed the raw error text; old scans were cleaned up by a migration. See e5 §3, "When a scan fails".
- **Endpoint:** `GET /banking/scans/{id}`.
- **Needed:** say whether `progress.is_complete` becomes true for a `FAILED` scan, and add a machine-readable failure `code` next to `error_message`.
- **Screen:** scanning.
- **App today:** stops polling on either `is_complete` or a final status, and shows `error_message` (or a fallback) with "Try Again".

#### BANK-10 · minor · Onboarding progress after skip and disconnect
- **✅ Fixed**: the bank step is now sticky. It counts as complete once the account has ever linked a bank, so disconnecting (or the bank asking for a fresh sign-in) no longer sends the user back into onboarding. `skip-bank` already answers with the updated progress, the same body as `GET users/onboarding`, so there is no need to refetch. See e2 §6.
- **Endpoint:** `GET /users/onboarding`, `POST /users/onboarding/skip-bank`.
- **Needed:** say whether the bank step goes back to incomplete after a disconnect (a sticky "was completed" flag would avoid re-prompting), and return the updated progress from `skip-bank`.
- **Screen:** onboarding gate.
- **App today:** calls `skip-bank` in the background (retried twice) and closes the flow at once. It ignores the answer, then refetches `users/onboarding`.

#### BANK-11 · minor · `provider` casing
- **✅ Fixed**: `LinkToken.provider` is now upper case (`"MOCK"`, `"PLAID"`), matching `BankConnection.provider` and the API's other enums.
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
- **✅ Fixed**: the routes are now `POST /notifications/devices/register` and `POST /notifications/devices/unregister`, with no trailing slash. The broken `/notificationsdevices/…/` paths are gone. The realtime guide (e8) now uses these paths too.
- **Endpoint:** `POST /notificationsdevices/register/`, `/notificationsdevices/unregister/`.
- **Today:** the routes have no `/` after `notifications` and end with a trailing slash. The documented `/notifications/devices/register/` is a 404. Observed (401 on the broken path, 404 on the documented one).
- **Needed:** `/notifications/devices/register` and `/notifications/devices/unregister`, without a trailing slash, like every other route.
- **Screen:** none yet. Push is not integrated.

#### DASH-3 · major (before realtime is enabled) · WebSocket
- **✅ Fixed (code and docs) — server setup still needed**: the socket now accepts `Authorization: Bearer <access JWT>` on the handshake, so the token stays out of the URL (the SEC-4 ask for native clients). Such a handshake skips the browser origin check. That check would otherwise have refused the app in production, because React Native sends no `Origin` header, or the API host as `Origin`. Browsers keep using `?token=` and the origin check. The guide no longer hard-codes `api.getswayp.com`; the socket is `wss://<api host>/ws/notifications/`. **Still needed on dev and staging (server work, not code):** run the `websocket` (daphne) service, add the nginx `/ws/` route from `docs/deployment.md`, and set `REALTIME_ENABLED=true`. Until then the dev host answers 404. See e8 realtime §2.1.
- **Endpoint:** `wss://…/ws/notifications/?token=`.
- **Today:** the dev host has no WebSocket route (HTTP 404). The guide's URL uses `api.getswayp.com`. The access JWT travels in the query string; see [SEC-4](#sec-4--major--websocket-sends-the-access-token-in-the-url).
- **Needed:** the route on dev and staging, and a safer handshake.
- **Screen:** none yet. Realtime is not integrated.

#### DASH-4 · minor · Unread count
- **✅ Fixed**: `GET /notifications` now has a top-level `unreadCount` next to `pagination`. It ignores the list's filters, so it is the bell badge. `GET /dashboard/home` has `unread_notification_count`, the signed-in person's count, the same as `profile-summary`. The home screen no longer needs to poll the profile summary. See e8 §1 and §4.
- **Endpoint:** `GET /notifications`, `GET /dashboard/home`.
- **Today:** the count exists only in `/dashboard/profile-summary`. `GET /notifications/unread-count` is a 404.
- **Needed:** `unreadCount` next to `pagination` in the list, and in `dashboard/home`.
- **Screen:** home bell, notifications.
- **App today:** the bell polls the profile summary every 60 s while home is focused. "Mark all read" shows when any loaded row is unread, so the badge and the list can disagree.

#### DASH-5 · minor · Mark-read answers
- **✅ Fixed**: `PATCH /notifications/{id}/read` returns the updated row in `data` (`isRead`, `readAt`) and a top-level `unreadCount`. `PATCH /notifications/read-all` returns `data.markedCount` and `unreadCount` (0). Re-reading an already-read notification is a 200 that keeps the original `readAt`. Another person's or an unknown id is 404. See e8 §4, "Marking read".
- **Endpoint:** `PATCH /notifications/{id}/read`, `PATCH /notifications/read-all`.
- **Needed:** return the updated row (`isRead`, `readAt`) and the new unread count. Document what re-reading a read notification returns, and the 404 rule.
- **App today:** updates the list optimistically, rolls back on error, handles a 404 quietly, then refetches the unread count.

#### DASH-6 · minor · Notification `metadata` is untyped
- **✅ Fixed, and a push bug found under it**: REST `metadata` keys stay snake_case, and the keys for each `type` are now documented (e8 §4). Every id is a uuid string or absent, never `""`: before, a payment with no bill sent `"bill_id": ""`. OpenAPI now declares `type` as the enum. **The bug:** push looked for camelCase keys (`paymentId`, …) that no code ever set, so every real push carried only `type` and `notificationId`, with no ids to deep-link from. It now copies the ids from the same data and renames them to camelCase (`billId`, `occurrenceId`, `paymentId`, `feeChargeId`). So push is camelCase and REST is snake_case, both documented.
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
- **✅ Fixed**: `GET /notifications` now takes `before=<notification id>` and returns the rows older than it, newest first. Every response carries `nextCursor`, the id to pass next or `null` on the last page, including the first page loaded with `page`. A row arriving mid-scroll no longer repeats or hides one. Also fixed: a `page` past the end used to return the last page again; it now returns an empty list, on every paged endpoint. See e8 §4.
- **Endpoint:** `GET /notifications`.
- **Today:** a new notification shifts every page, so rows are duplicated or skipped between pages.
- **Needed:** a cursor (`before=<id or createdAt>`).
- **App today:** removes duplicates by id.

#### DASH-8 · minor · `vendors_preview` is missing the next due date, and `monthly_amount` is unclear
- **✅ Fixed**: each `vendors_preview` row now has `next_due` (date or `null`), `recurring_amount` and `amount_period`: the vendor's next unsettled bill, as on `GET /vendors`. `monthly_amount` is documented: bills due in the **current calendar month** (US Eastern), paid or not. That is why WeWork showed `0.00`: its next bill fell next month. The list is at most 3 vendors, highest `monthly_amount` first, then by name. See e8 §1, "Vendor cards".
- **Endpoint:** `GET /dashboard/home` → `vendors_preview[]`.
- **Today:** no next due date. A captured body shows `monthly_amount: "0.00"` for a vendor billed $3,200 a month.
- **Needed:** `next_due` (date or null). Document what `monthly_amount` measures, and the order and limit of the list.
- **Screen:** home, My Providers cards.
- **App today:** the card's "Last Date:" line became "This month:" with `monthly_amount`.

#### DASH-9 · minor · Funding account on the home dashboard
- **✅ Fixed**: `GET /dashboard/home` now has `funding_account: { id, name, mask, display } | null`. It is the account a payment would debit, chosen by the same rule `POST /payments` uses. `null` means a payment would be refused for lack of a bank. See e8 §1, "Funding account".
- **Endpoint:** `GET /dashboard/home`.
- **Needed:** `funding_account: { id, name, mask, display } | null`. It already exists in `banking/onboarding-summary`.
- **Screen:** home, Details Confirmation card ("From").
- **App today:** the "From" row is static design content.

#### DASH-10 · minor · Document `recent_bills` and the pay panel
- **✅ Documented**: `recent_bills` is up to 5 occurrences due today or earlier (US Eastern), any status, newest due date first. `pay_panel.items` is up to 5 rows of the active tab only, earliest due first. `pay_panel.tabs` has the full count for every tab, and `bills/occurrences?status=` returns the rest in the same order. Also in the OpenAPI field descriptions. See e8 §1.
- **Endpoint:** `GET /dashboard/home`.
- **Needed:** the selection rule, order and limit of `recent_bills`, and the page size and order of `pay_panel.items`.
- **App today:** `pay_panel.items` holds only the server's active tab, so Payment Centre shows that tab's rows (up to 5, earliest due first).

#### DASH-11 · minor · Profile and greeting
- **✅ Fixed**: `GET /users/profile` (and the `PATCH` answer) now has `id`, the account the profile describes. For a team member that is the business, and their own id is in `profile-summary`. `greeting` is kept and documented: one of four fixed strings, picked by the hour in US Eastern time (Morning 05–12, Afternoon 12–17, Evening 17–21, Night otherwise). Computing it from the device clock, as the app does, is right for users outside Eastern. The profile still has no avatar; that is AUTH-13. See e2 §5 and e8 §1.
- **Endpoint:** `GET /users/profile`, `GET /dashboard/profile-summary`.
- **Today:**
  - The profile has no `id` and no avatar.
  - `greeting` in the summary has an undocumented format and timezone.
- **Needed:** an `id` on the profile, and either documentation for `greeting` or its removal.
- **Screen:** home header.
- **App today:** the avatar comes from the summary's `profilePicture` (https only). The greeting is computed from the device clock.

#### DASH-12 · product decision · The design has a wallet, the API has none
- **🚫 Obsolete**: the wallet has been dropped from the product, so there is nothing to build. Remove the balance card, the "Balance" pill, "From My Wallet / Wallet Number", and the wallet tab's Add Funds, Transfer Fund and deposit history. Where the home screen needs real figures instead, use `stats.due_this_month` ("Due this month") and `funding_account.display` for "From" (DASH-9).
- **Endpoint:** none (`GET /wallet` is a 404, and E6 §1.3 says there is no wallet by design).
- **Today:** the home balance card ($12,547.80), the "Balance" pill and "From My Wallet / Wallet Number" are design content with no data behind them. So are the wallet tab's Add Funds, Transfer Fund and deposit history.
- **Needed:** a product decision, not an endpoint. Either the labels change (for example "Due this month"), or product keeps a stored-value wallet, which would need a ledger the backend says it will not hold.
- **App today:** the product owner deferred the wallet. These parts stay as designed, with static values.

---

## Bills

#### BILLS-1 · major · Bill create and update have no schema, and the guides disagree on `frequency`
- **✅ Fixed**: OpenAPI now declares the request bodies and the responses: create **201**, update **200**, both with the review object, and the `frequency`, `bill_type`, `autopay_mode`, `source` and `payment_method` enums. The `frequency` answer is **`MONTHLY · QUARTERLY · WEEKLY · ONE_TIME`**, as the bills reference and `CadenceEnum` say. e4 was wrong and now matches. See e4 §4.
- **Endpoint:** `POST /bills/create`, `PATCH /bills/{id}/update`.
- **Today:**
  - OpenAPI has no request body and answers "200 No response body". The docs say 201 with a review summary.
  - e4 lists `WEEKLY · BIWEEKLY · MONTHLY · QUARTERLY · YEARLY`. The bills reference and `CadenceEnum` list `MONTHLY · QUARTERLY · WEEKLY · ONE_TIME`.
- **Needed:** publish the request and response schemas, with the `frequency`, `bill_type`, `autopay_mode` and `source` enums and the 201.
- **Screen:** the add-bill wizard (and edit, which is not built yet).
- **App today:** sends `vendor`, `category`, `payment_method`, `anchor_date` and `frequency` ∈ `MONTHLY | QUARTERLY | WEEKLY | ONE_TIME` (the four Figma chips) as documented in the bills reference. It accepts any 2xx.

#### BILLS-2 · major · QR decode returns names instead of ids
- **✅ Fixed**: `POST /bills/qr/decode` now returns `vendor_id` (the account's saved vendor with that exact name, or `null`) and `category_id` (the active category the QR names, else the matched vendor's category, or `null`), next to the names. OpenAPI declares the response, and `amount` is a decimal string. Both QR routes now answer a 422 as `{ success: false, message }`; `vendors/qr/decode` used to send `{ detail }`. See e4 §7.
- **Endpoint:** `POST /bills/qr/decode`.
- **Today:**
  - The response has `vendor_name` and `category` as names.
  - There is no response schema.
  - The 422 body is `{ success, message }`, while the vendors twin answers `{ detail }`.
- **Needed:** `vendor_id` (the matched saved vendor, or null) and `category_id`, a response schema, and one 422 shape.
- **Screen:** QR scanner → add-bill wizard.
- **App today:** puts the vendor name in the vendor search box and matches the category by name. Scanned values are marked "Read from the QR code. Please confirm."

#### BILLS-3 · major · The server should write the autopay authorization text
- **✅ Fixed**: `POST /bills/autopay-authorization/preview` with `{ vendor, amount, bill_type, frequency, anchor_date, payment_method? }` returns `authorization_text` (plus `funding_account`). Show it and send it back verbatim as `autopay_consent.authorization_text`. The text names the account debited, the amount (for variable bills, "the amount due on each bill"), the schedule and start date, the vendor, the processor, and how to revoke. Call it again when an autopay bill's terms change (BILLS-4). See e4 §4, step 5. The wording should still get a legal review before production.
- **Endpoint:** new, for example `POST /bills/autopay-authorization/preview` (vendor, amount, frequency, bill type, date, funding account).
- **Today:** the payments API returns its authorization text, but bill create expects the client to compose the NACHA sentence for `AUTO` bills.
- **Needed:** the exact `authorization_text` from the server, which the app then shows and sends back verbatim.
- **Screen:** add-bill review → "Authorize auto-pay" sheet.
- **App today:** composes the sentence on the client. It still needs legal review.

#### BILLS-4 · major · What happens to an autopay authorization after an edit?
- **✅ Fixed (it was a real gap)**: before, the old authorization silently stayed valid, so a user who agreed to $389 a month could be debited a different amount under the same consent. Now a PATCH to an `AUTO` bill that changes `amount`, `frequency`, `anchor_date`, `bill_type` or `payment_method` must carry a fresh `autopay_consent`. Without it, it is a 400 and nothing is saved. With it, the old authorization is revoked and the new one recorded. `notes`, `category` and `source` need no consent. See e4 §5, "Editing an autopay bill needs fresh consent".
- **Endpoint:** `PATCH /bills/{id}/update`.
- **Needed:** document whether a stored authorization stays valid when `amount`, `frequency`, `anchor_date` or `payment_method` of an `AUTO` bill changes, or whether fresh consent is required.
- **Screen:** edit bill (not built yet).

#### BILLS-5 · major · Bill detail is missing ids and uses numbers for money
- **✅ Fixed**: `GET /bills/{id}/details` now has `vendor_id`, `category_id`, `payment_method_id` and the masked `account_ref`. It also has `next_occurrence: { id, due_date, amount, status } | null` (the occurrence `next_due` describes) and `last_paid_at`. `overdue_amount` and `total_paid` are now decimal strings (`"0.00"` when zero), not numbers. See e4 §5.
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
- **⏸ Valid, a new feature; not built.** Upload and OCR need an OCR provider, file storage and a review flow (extracted fields, each with provenance, confirmed by the user). This is its own piece of work, to be scoped separately. The Upload to Import screens stay on demo data until then.
- **Endpoint:** new, for example `POST /bills/import/document` (photo or PDF → vendor, amount, due date, reference, with provenance).
- **Today:** there is no upload, OCR or import route under `bills`. `POST /bills/upload` and `POST /bills/import` are 404s (observed).
- **Screen:** Upload to Import (`(import-bill)/upload`, `details`).
- **App today:** these screens stay on demo data.

#### BILLS-7 · major (product + API) · The consumer utility flows have no backing
- **⏸ Product decision; no API work.** None of this exists, and the app has already removed the entry points. Unless product brings the consumer utility flows back, treat them as dropped. If it does, the meter or account reference, biller lookup and amount-due lookup need their own spec first.
- **Endpoint:** none exists.
- **Today:** the electricity, capture and manual-bill flows need a meter or customer-account reference on a vendor or bill, biller-account validation, an amount-due lookup, and account-holder and phone fields. None exist, and there is no wallet to pay from.
- **Needed:** confirm that these flows are dropped, or specify the endpoints.
- **App today:** Home's "Enter Bill Details" opens the add-bill wizard and its bill-type badges open that category's bills, so these demo flows have no entry point any more.

#### BILLS-14 · major · Bill occurrences cannot be filtered by category
- **✅ Fixed**: `GET /bills/occurrences` takes `category` (category id; several allowed), combinable with `status` and the other filters, and every row carries `category_id`. The category screen no longer needs to page through everything or match on names. Not done: the optional count per category. Ask if the Home badges still need it. See e4 §3.
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
- **✅ Fixed**: each occurrence row now has `payment_method` (the bill's method type or `null`), `days_overdue` (calendar days on an `OVERDUE` row, else 0, the same as bill detail) and `payment_id` (the payment behind a `SCHEDULED` or `PAID` row). `status` takes several values (`?status=OVERDUE,DUE` or repeated), and the order is documented: `due_date`, earliest first. `bills/summary` has `scheduled_count`. The same rows feed the home pay panel and recent bills. See e4 §3.
- **Endpoint:** `GET /bills/occurrences`, `GET /bills/summary`.
- **Needed:**
  - On each row: `payment_method` (or the default `rail`), `days_overdue`, and the `payment_id` of the active payment for `SCHEDULED` and `PAID` rows.
  - A multi-value `status` (or `unsettled=true`), with a documented order.
  - `scheduled_count` in the summary.
- **Screen:** Pay tab, schedule strip, a future bills list.
- **App today:** the Pay tab loads one list per pill (Overdue / Due / Upcoming). The schedule strip fetches bill detail to get `days_overdue`.

#### BILLS-9 · minor · Category codes
- **✅ Fixed (no `code`; `displayOrder` is the key)**: product chose `displayOrder` over a new `code`. It is now **unique** in the database, so it is stable for picking and ordering Home's badges, and renaming a category cannot reorder them. A migration renumbered existing categories 1..n in their current order, so nothing visibly moved. A new category with no order goes to the end. e1 now spells it `displayOrder`, as the API sends it. Pick a badge's artwork by `id` or `displayOrder`, not by keywords in the name.
- **Endpoint:** `GET /bill-categories`.
- **Today:** no stable `code`. e1 documents `display_order`, but the API sends `displayOrder`.
- **Needed:** a stable `code`. `displayOrder` now decides which categories a user sees first, so please also confirm it is meant to be stable and unique.
- **Screen:** Home bill-type badges.
- **App today:** the badges are the first four categories by `displayOrder`. Which of the four drawings a badge gets is decided by keywords in the category's name ("electric", "power", "energy", "utilit" → the electricity badge, and so on); any other category gets a plain badge in its own `color`. A renamed category silently changes its artwork.

#### BILLS-10 · minor · No field for a scanned payment reference
- **✅ Fixed**: bills have a `payment_ref` field (up to 100 characters), accepted by create and update and returned by bill detail. Send the QR's `payment_ref` there instead of `"Ref …"` in `notes`. See e4 §4.
- **Endpoint:** `POST /bills/create`.
- **Needed:** a field for the decoded `payment_ref`.
- **App today:** writes it into `notes` as "Ref …".

#### BILLS-11 · minor · Document the create rules
- **✅ Fixed and documented**: a table of every create rule is now in e4 §4, "What create checks". Answers: an omitted `payment_method` means **none** (autopay then uses standard ACH). Lead time is **not** checked; use the method `schedule`. A past `anchor_date` **is** accepted and creates the current period's occurrence, never a backlog. `amount` is ≥ 0.01. `notes` is now capped at 2,000 characters. `AUTO` does **not** need a connected bank to create, but runs fail without one. Tightened: an inactive category or a deleted vendor is now refused with a field error (it was accepted, or a bare 404). A per-method `earliest_due_date` is not added; the `schedule` already gives it.
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
- **✅ Answered from the code**: ① **Yes**, `source: "QR"` is accepted on create; the bill `source` enum is `MANUAL`, `QR` or `DETECTED`. ② **Yes**, `GET /bills/next-due` answers **200 with `data: null`** when nothing is outstanding. ③ **No**, `GET /bills/occurrences/upcoming` does **not** include overdue rows: it returns occurrences due today or later that are not yet scheduled or paid. The e4 wording that caused the disagreement is fixed. For "everything still to pay", use `bills/occurrences?status=OVERDUE,DUE,UPCOMING` (BILLS-8).
- Is `source: "QR"` accepted on create? (`SourceEnum` in OpenAPI is the vendor one.) The app sends it for scanned bills only.
- Does `GET /bills/next-due` answer 200 with `data: null` when nothing is outstanding? The success screen hides "Next up" then.
- Does `GET /bills/occurrences/upcoming` include overdue rows? The two docs disagree.

#### BILLS-13 · minor · Screens not built yet
- **⏸ Deferred until the screens are built.** Raise each one again with the screen that needs it. `GET /providers` → vendor waits on the NETWORK vendor contract in VEND-6.
These matter once the bill detail screens are built:
- `GET /bills/{id}/invoice`: invoice number and date, vendor address, bill-to block, line description and tax. Or confirm the invoice screen should drop them.
- `GET /bills/{id}/payments`: a `status` filter, counts per status, and the masked account of the method used.
- `GET /providers`: a catalogue row cannot become a vendor. There is no `network_payee_ref`, no detail route, and the NETWORK vendor contract is unclear ([VEND-6](#vend-6--major--directory-search-and-network-vendors-are-undefined)).

---

## Payments

#### PAY-1 · major · An unconfirmed payment strands its bill
- **✅ Fixed** (and it was worse than reported: for pay now, the cancel deadline had already passed when the payment was created, so an abandoned one could **never** be cancelled). Now:
  - an **unconfirmed payment can always be cancelled**; the deadline applies only after confirm;
  - **unconfirmed payments lapse after 30 minutes**: a job every 5 minutes cancels them and releases their bills;
  - `GET /payments/{id}` has `authorized_at` (`null` = not confirmed), `authorization_text` and `confirm_by`.

  Confirmed: ✅ the `AUTHORIZED` stage becomes `DONE` only at confirm (autopay marks it from the standing authorization). ✅ `POST /payments` with one occurrence returns `batch_id: null` and exactly one payment. The keychain marker can stay as a fast path, but the server now cleans up on its own. See e6 §1.1 and §3.
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
- **✅ Fixed**: `docs/payments-api-documentation.md` now exists: statuses, stages, rails, and every endpoint's body, idempotency and test amounts. The guides that linked to "Payments API" now point to it. OpenAPI declares a response body for every payments endpoint, including status, batch status, confirm, cancel, failure and resolve. `receipt`, `failure` and `progress` on `PaymentDetail` are proper objects, not `string`. The family uses the standard `{ success, message, data }` envelope throughout.
- **Endpoint:** `GET /payments/{id}/status`, `GET /payments/batches/{id}/status`, `GET /payments/{id}/failure`, `POST …/confirm`, `POST …/cancel`, `POST …/resolve`, and the `receipt`, `failure` and `progress` blocks of `PaymentDetail` (typed `string` in OpenAPI).
- **Today:** the guide links a "Payments API" document that is not in the repo. None of these bodies are documented, and the envelope of the payments family is unstated.
- **Needed:** the reference with captured bodies, and OpenAPI response schemas.
- **Screen:** processing, failed / resolve, payment detail.
- **App today:**
  - Types these bodies as unknown and reads them defensively.
  - The failure reason comes from the failed stage's detail. `GET /payments/{id}/failure` is not used.
  - Polls `GET /payments/{id}`, not `/status`.

#### PAY-3 · major · Payment history rows lack the vendor
- **✅ Fixed**: history rows now have `vendorId`, `vendorName`, `billId`, `occurrenceId`, `rail`, `estimatedArrival`, `scheduledFor` and `replacedPaymentId` (the failed payment this one retried). **`providerName` does not carry the vendor.** It is the biller-directory provider, usually `null` for bill payments, so show `vendorName` as "Recipient". Rows stay camelCase; switching them to snake_case would break current clients, so that is left for API-5. See e6 §5.
- **Endpoint:** `GET /payments/history`.
- **Today:** rows have `providerName` (documented as nullable) and no vendor fields. Rows are camelCase while every other payment body is snake_case.
- **Needed:**
  - `vendor_id`, `vendor_name`, `bill_id` and `occurrence_id`.
  - `rail`, `estimated_arrival`, `scheduled_for` and `replaced_payment_id`.
  - Confirm whether `providerName` carries the vendor for bill payments.
- **Screen:** payment history.
- **App today:** "Recipient:" shows `providerName`, or a dash when it is null.

#### PAY-4 · major · A payment or occurrence cannot be traced back to its bill or vendor
- **✅ Fixed**: every payment body (create, detail, status, cancel, resolve) now has `vendor_id`, `bill_id`, `funding_account_id` and `payment_method_id`, next to `bill_occurrence`. New `GET /bills/occurrences/{occurrence_id}` returns one occurrence in the list's row shape, including `bill_id`, `vendor_id`, `status` and `payment_id`; it is 404 if the occurrence is not the account's. Notification links with an `occurrence_id` or `bill_id` can now open the bill, and "Choose payment method" has the ids it needs. See e6 §2.
- **Endpoint:** `GET /payments/{id}`, and a new `GET /bills/occurrences/{occurrence_id}`.
- **Needed:** the occurrence route, and `vendor_id`, `bill_id`, `funding_account_id` and `payment_method_id` on `PaymentDetail`.
- **Screen:**
  - Failed → "Choose payment method".
  - Notification deep links that carry an `occurrence_id` or `bill_id`.
  - Payment detail → bill.
- **App today:** those notifications open the Pay tab. "Choose payment method" shows "Changing the payment method is not available yet."

#### PAY-5 · major · Rail choice
- **✅ Fixed, except the per-occurrence rail in a batch**:
  - **Default:** an omitted `rail` now means **each bill's own rail**, from its saved payment method, as autopay does. It used to be `ACH_STANDARD` for everything, so pay now on a check-only vendor went out on a rail it cannot receive. When omitted, a batch can mix rails.
  - An explicit `rail` has to suit the bill's method, otherwise 400 on `errors.rail`.
  - **New `POST /payments/quote`:** for each occurrence, every rail with `available` and an `unavailable_reason`, the `fee`, `initiated_date` and `estimated_arrival`, the expedited option for checks, and `default_rail`. It handles the same-day cutoff and creates nothing.
  - **Not done:** choosing a *different* explicit rail per occurrence within one batch. Omitting `rail` already gives each bill its own; ask if a per-occurrence override is still needed. See e6 §2, step 1 and "Quote first".
- **Endpoint:** `POST /payments`.
- **Needed:**
  - Say what `rail` defaults to when omitted: the bill's saved method, or always `ACH_STANDARD`?
  - Allow a rail per occurrence in a batch.
  - Return the offer before create (`available_rails[{ rail, fee, estimated_arrival, available }]`, or a quote endpoint), so the client can show fees and hide same-day after the cutoff without computing Eastern time.
- **Screen:** summary, schedule.
- **App today:** omits `rail` when the bill has no saved method type, and shows the fee only after create.

#### PAY-6 · minor · Failure and resolve bodies
- **✅ Fixed, and a bug found**:
  - `GET /payments/{id}/failure` already had `due_date`, `days_overdue`, `late_fee` and `available_actions`, but undocumented. It now also has a display-ready **`title`** and **`explanation`** per failure reason, and OpenAPI declares it all.
  - **Resolve (201):** answers with the new payment, `replaced_payment_id`, **`authorization_text`** and `requires_confirmation: true`. The new payment is unconfirmed, so always go to Confirm with that text; before, it came back with no text to confirm.
  - **Casing:** lowercase is correct (`retry`, `change_method`, `reschedule`). e6's `"RETRY"` was wrong and is fixed.
  - **The bug:** `change_method` kept the failed payment's rail, so switching from an ACH account to a check would have sent the payment over ACH. It now uses the new method's rail.

  See e6 §4.
- **Endpoint:** `GET /payments/{id}/failure`, `POST /payments/{id}/resolve`.
- **Needed:**
  - A failure body with a display-ready `title` and `explanation`, `due_date`, `days_overdue`, a late-fee block and `available_actions`.
  - A resolve response that is the new payment (with `replaced_payment_id`), plus `authorization_text` when new consent is required.
  - e6 shows `action: "RETRY"`, while OpenAPI declares `retry | change_method | reschedule`. Which casing is right?
- **Screen:** failed.
- **App today:** sends lowercase actions. It reads the resolve body on a best-effort basis and compares the returned id with the failed one. With a new authorization text it opens Confirm, otherwise Processing.

#### PAY-7 · minor · Reschedule in place
- **✅ Fixed**: `PATCH /payments/{id}` with `{ scheduled_for }` moves an unconfirmed payment to a new date in place: same payment and reference, recomputed dates, and the answer is the payment detail. `null` means pay now. The date must be today or later. **Non-business days are accepted** for `scheduled_for`; the dates count from it in business days. A confirmed payment cannot be moved (400), because its date was authorized. See e6 §2, "Changing the date before confirming".
- **Endpoint:** `POST /payments` + `cancel`, or a new `PATCH` of `scheduled_for`.
- **Needed:** reschedule an unconfirmed payment without cancel + create. Say whether non-business days are accepted for `scheduled_for`.
- **Screen:** schedule.
- **App today:** cancels the pay-now payment and creates a scheduled one.

#### PAY-8 · minor · Receipt file
- **✅ Fixed**: `GET /payments/{id}/receipt.pdf` returns the receipt as a PDF download (reference, payee, date, account, method, amount, fee, total) for a `SUCCESSFUL` payment, and 409 before that. It needs the usual auth header. See e6 §2, step 4.
- **Needed:** a receipt (PDF) for a settled payment.
- **Screen:** payment detail → "Download Receipts".
- **App today:** shares a plain-text receipt built from the payment detail.

#### PAY-9 · minor · Test hooks on the mock processor
- **🟡 Documented; slow stages deferred**: the mock processor already picks the outcome from the amount's cents. **`.01` gives an `NSF` failure**, with the balance in `failure_detail`. **`.02` loses the response**: it stays `PROCESSING` until the reconcile job completes it, about 30 minutes later. Anything else succeeds at once. See e6 §7b. A deliberately slow but successful outcome is not added: the execution engine treats any result that is not `SUCCESSFUL` as a failure, and there is no real processor integration yet (only the mock) to design an in-progress path against. That comes with the first real provider.
- **Needed:** a documented way to force `FAILED` and slow stages on the mock processor.
- **Screen:** processing, failed (QA).

---

## Vendors

#### VEND-1 · blocker · No way to obtain an ACH payee token
- **⏸ Blocked on Stripe Treasury access; dev convention documented.** ACH is Stripe (PRD D-1). The tokenization flow is part of the Treasury integration, which is on hold until Stripe grants access (`docs/stripe-treasury-integration-plan.md`). It will be **server-side**: the app sends the numbers to Swayp once, and Swayp exchanges them with Stripe and keeps only the token and last 4. **Dev answer:** yes, the dev API accepts `pm_mock_<uuid>`. Send `provider: "STRIPE"` (not `MOOV`) with any unmasked token; payments run on the mock processor and never use it. Release builds should stay on check and directory vendors until then. See e3 §4.
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
- **✅ Fixed**: the add-method `POST` already returned the read shape (`id`, `account_ref`, no token); **OpenAPI was wrong** and now matches. Two real fixes: `PATCH` on a method used to echo **`provider_token`** and now returns the read shape, and **a vendor's first method becomes primary automatically**, so the extra `set-primary` call isn't needed. See e3 §4.
- **Endpoint:** `POST /vendors/{id}/payment-methods`.
- **Today:** per the schema, the 201 body has no `id` and no `account_ref`, and it echoes `provider_token`. The new method is not made primary even when the vendor has no primary.
- **Needed:**
  - Return the read shape (`VendorPaymentMethod`) and never echo the token.
  - Auto-promote a vendor's first method, or honour `is_primary`.
- **Screen:** linked details → add payment details.
- **App today:** refetches the vendor, finds the new method and calls `set-primary`.

#### VEND-3 · major · Vendor create may not return the vendor
- **✅ Fixed (the schema was wrong)**: `POST /vendors` already answers **201 with the full vendor**, `id` and `payment_methods[0].account_ref` included, as the guide said. OpenAPI now declares that. The "Vendor saved" success screen can use the `id`. See e3 §4.
- **Endpoint:** `POST /vendors`.
- **Today:** the schema says the 201 body echoes the request with no `id`. The guide shows the full vendor.
- **Needed:** the full vendor with `id` and `payment_methods[0].account_ref`. Please fix whichever source is wrong.
- **Screen:** add a payee → "Vendor saved".
- **App today:** without an `id` there is no success screen: the app shows a "Vendor saved" toast and closes the wizard.

#### VEND-4 · major · Vendors have no contact fields
- **✅ Fixed**: vendors now have `contact_name`, `contact_phone` and `contact_email`. They are returned on detail, writable by `PATCH /vendors/{id}` and accepted on create, and `""` when unset. They are records only; Swayp sends nothing to them. See e3 §3.
- **Endpoint:** `GET /vendors/{id}`, `PATCH /vendors/{id}`.
- **Today:** the detail design has Contact Person, Phone Number and Email Address, but the API has no such fields.
- **Needed:** `contact_name`, `contact_phone` and `contact_email` (read + PATCH), or confirmation that the design drops them.
- **Screen:** linked details.
- **App today:** three of the six fields show "Not available".

#### VEND-5 · major · No vendor activity feed
- **✅ Fixed**: new `GET /vendors/activity?page=&pageSize=`, newest first, with `{ items, pagination }`. Each row: `action`, a display `label`, `vendor_id`, `vendor_name` (as it was at the time), `actor_name` (`null` for bank imports) and `created_at`. It records vendor added, updated, removed and restored, and payment method added, changed, removed and primary changed. List rows already gained `created_at` and `updated_at` (VEND-8). Recording starts now, so there is no backfill. See e3 §7b.
- **Endpoint:** new, for example `GET /vendors/activity?page=`.
- **Today:** there is no feed of vendor events (linked, updated, removed, with timestamp and vendor name), and list rows have no `created_at` or `updated_at`.
- **Screen:** recent activities.
- **App today:** this screen stays on demo data.

#### VEND-6 · major · Directory search and NETWORK vendors are undefined
- **✅ Fixed — one contract**: the real hit shape is the schema's, `external_id, name, category, verified, speed, network`, plus a new **`category_id`** (the matching Swayp category or `null`). The vendors doc's `provider_name`/`provider_code` shape was stale and is replaced. **A NETWORK vendor needs `network_payee_ref`**, not `provider` and `provider_token`; e3's table was wrong. Mapping: `name` → `name`, `category_id` → `category` (omit when null), `external_id` → `payment_method.network_payee_ref`, `source: "DIRECTORY"`. The vendor records which directory biller it is. `q` is declared, and an empty `q` returns nothing. See e3 §5.
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
- **✅ Fixed**: `category` is optional on `POST /vendors`. Left out, the vendor is filed under the default category ("Other", the same default a bank-scan import uses). The added picker can go, or stay optional. An inactive category is refused. See e3 §1.
- **Endpoint:** `POST /vendors`.
- **Needed:** make `category` optional with a server default, or confirm that the app's added picker is the intended design.
- **App today:** "Add Manually" has an added Category field that is required before Continue.

#### VEND-8 · minor · Vendor list rows
- **✅ Fixed**: rows now have `status`, `category` (id), `category_name`, `created_at` and `updated_at`. **"Assigned Bill Payer" is dropped from the design** (product decision, 2026-10-10), so there is no field for it. See e3 §1.
- **Endpoint:** `GET /vendors`.
- **Today:** the card design shows "Assigned Bill Payer". No such field exists, and rows also lack `status` and a category name.
- **App today:** the card shows the payment method instead, and an "Active" pill.

#### VEND-9 · minor · Vendor update and detail bodies
- **✅ Fixed**: `PATCH /vendors/{id}` now answers with the **full vendor** (the detail shape). `total_paid`, `monthly_spend[].total`, `next_bill.amount` and `bills[].amount` are always 2-decimal strings. `bills[]` is documented and typed in OpenAPI: `occurrence_id, bill_id, category, amount, due_date, status`. Methods now carry `account_type` and `network_payee_ref`. See e3 §3.
- **Endpoint:** `PATCH /vendors/{id}`, `GET /vendors/{id}`.
- **Today:**
  - PATCH returns three fields (`name, category, notes`), not the vendor.
  - `total_paid` is sometimes a number.
  - `bills[]` items are undocumented.
  - The method read shape lacks `account_type` and `network_payee_ref`.
- **App today:** after PATCH it uses the values it sent, coerces `total_paid`, and never reads `bills`.

#### VEND-10 · minor · Error bodies for QR decode and routing validation
- **✅ Fixed**: the QR decode 422 is the standard envelope (BILLS-2). Routing validation's answers are documented in e3 §4: a bad number is a **200** with `valid: false` and a reason; a masked or empty value is a **400** on `errors.routing_number`; over 30/min is a **429**. Two bugs found and fixed: **the 429 was missing its `Retry-After` header**, on every endpoint using DRF's throttling, not only this one, and `"abc"` was told "Routing number is required." instead of "must be 9 digits".
- **Endpoint:** `POST /vendors/qr/decode`, `POST /banking/routing/validate`.
- **Today:** the QR 422 body is `{ detail }` instead of the standard envelope. For routing validation, the status and body for a masked or malformed number, and the 429 body and `Retry-After`, are undocumented.
- **Screen:** add a payee → bank details.
- **App today:** treats a 400 as "Routing number invalid", a 429 as a rate-limit message, and anything else as "unavailable".

#### VEND-11 · minor · Delete semantics
- **✅ Fixed, plus a bug found**: deleting a vendor only marked the vendor, so its bills stayed live. Occurrences kept being created, reminders kept going out, and **autopay kept paying the deleted vendor**. Now delete also deletes its bills: upcoming unpaid occurrences are dropped, autopay is revoked, paid history is kept. Delete **is** refused (400) while a payment is scheduled or in flight. New `POST /vendors/{id}/restore` undoes it: the bills that went with it come back **on REMIND**, because autopay needs fresh consent. Bills deleted separately stay deleted. Your "Its bills and payment history are kept" copy should become "Its upcoming bills stop; payment history is kept." See e3 §7.
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
- **✅ Fixed**: `GET /billing/payment-method` returns `{ brand, last4, exp_month, exp_year } | null`. `POST /billing/payment-method { payment_method_id }` (from a SetupIntent, `payment-method/setup`) replaces it, for the customer and the subscription. A **past-due** subscription is charged with the new card at once, which is the recovery path for BILLING-6. A declined card is a 400 on `payment_method_id`. Card entry still needs the Stripe SDK on the app side. See e9 §5b.
- **Endpoint:** new: `GET /billing/payment-method` → `{ brand, last4, exp_month, exp_year } | null` (or the same on `Subscription`), and `POST /billing/payment-method { payment_method_id }`.
- **Today:** nothing returns the card on file. `PATCH /billing/subscription` takes only `{ plan }`, so a trialing or past-due customer cannot add a card.
- **Screen:** subscriptions → payment ("Payment Method").
- **App today:** always shows "No card on file".

#### BILLING-2 · major · No invoice history
✅ Fixed: `GET /billing/invoices?limit=&starting_after=` lists past invoices from the processor, newest first: `{ id, number, status, total, currency, created, period_start, period_end, paid_at, pdf_url, hosted_url }`. Paging is by cursor (`next_cursor` beside `data`), because the processor pages that way. Empty on a deployment that collects no money.
- **Endpoint:** new: `GET /billing/invoices?page=&pageSize=` with `{ id, period_start, period_end, total, status, paid_at, pdf_url }`.
- **Today:** only the current-cycle preview exists.
- **Screen:** subscriptions → payment ("Billing History").
- **App today:** shows the current-cycle invoice plus billed fees.

#### BILLING-3 · major · Reading `collects_money` creates a SetupIntent
- **✅ Fixed**: new `GET /billing/config` returns `{ collects_money, publishable_key }` and creates nothing. Call `payment-method/setup` only when the card form is about to open. See e9 §1.
- **Endpoint:** `POST /billing/payment-method/setup`; new, for example `GET /billing/config`.
- **Today:** the only way to learn whether the provider takes real money (and the publishable key) is the setup call, which creates a SetupIntent every time.
- **Needed:** a call with no side effects.
- **Screen:** subscriptions checkout.
- **App today:** calls setup on every checkout press. When money is collected, only a trial plan can be started in the app: card entry needs the Stripe SDK, which is deferred. Other plans show "Card payment isn't available in the app yet".

#### BILLING-4 · major · Plan eligibility per account
- **✅ Fixed (and an abuse hole closed)**: every new subscription used to start a trial, so cancel and resubscribe gave **another free trial**. Now the trial is for an account's first subscription only. `GET /billing/plans` adds, per account, `trial_eligible`, `lock_available` and `founding_spots_remaining`. See e9 §5, "The 14-day trial".
- **Endpoint:** `GET /billing/plans`.
- **Today:** `trial_days` and `price_locked` are properties of the plan. The app cannot tell a returning customer, or customer number 501, that the offer no longer applies.
- **Needed:** `trial_eligible` and `lock_available` (or `founding_spots_remaining`) per account.
- **Screen:** choose plan (badge), payment (CTA).

#### BILLING-5 · major · Cancellation semantics
- **✅ Fixed (cancel at period end)**: `DELETE /billing/subscription` used to end the plan **immediately with no refund**. Now the plan stays `ACTIVE` until `cancels_on` (the end of the paid month, or the trial's end), then ends; there is no refund because nothing is lost. The body has `cancel_pending: true` and `cancels_on` (the "ends at" date). New `POST /billing/subscription/resume` undoes it. Treat the cancel as "scheduled", not "cancelled". See e9 §5.
- **Endpoint:** `DELETE /billing/subscription`.
- **Needed:** document whether access ends immediately and whether anything is refunded. Return `ends_at`. Cancel at period end is preferred.
- **Screen:** subscriptions → cancel confirmation.
- **App today:** treats any 2xx as cancelled.

#### BILLING-6 · major · `PAST_DUE` and `provider_status` are undocumented
- **✅ Fixed (and a bug found)**: a past-due account used to look **planless**: `GET subscription` answered `null`, limits and fees fell back to the no-plan rules, and **subscribe opened a second subscription**. Now `PAST_DUE` counts as the live plan. `GET` returns it with `past_due: true`, allowances still apply, and a second subscribe is a 400. **Recovery:** Stripe retries the charge, or the owner replaces the card (`POST /billing/payment-method`, BILLING-1); either returns it to `ACTIVE`. If Stripe gives up, it becomes `CANCELLED`. `provider_status` is Stripe's raw status string, for support use only; branch on `status` and `past_due`. See e9 §5, "Past due".
- **Endpoint:** `GET /billing/subscription`.
- **Needed:** when these occur (mock and Stripe), whether `GET subscription` still returns the row, whether allowances still apply, and how the customer recovers (depends on BILLING-1).
- **Screen:** subscriptions index banner.
- **App today:** shows a past-due banner.

#### BILLING-7 · major · Plan change when usage exceeds the target plan
- **✅ Fixed**: a downgrade used to go through even when the account was over the new plan's limits. Now it is a **402** naming each limit, for example *"3 connected banks in use, Founding allows 1"*, and nothing changes. It covers seats (pending invitations count) and banks; checks reset monthly and never block. A change with no subscription is a **400** on `errors.subscription`. BILLING-11 adds a machine-readable `code` to the 402. See e9 §5.
- **Endpoint:** `PATCH /billing/subscription`.
- **Needed:** define the status code and a displayable message for a downgrade below current usage (seats, banks), and for a change with no subscription.
- **Screen:** manage plan.
- **App today:** warns before a downgrade with its own copy, then shows the server's message.

#### BILLING-8 · minor · Plan display content
✅ Fixed: each plan carries `description`, `features` (display-ordered lines, the numeric ones generated from the plan's own limits) and `billing_interval: "month"`. There is no annual price.
- **Endpoint:** `GET /billing/plans`.
- **Needed:** `description`, `features: string[]`, and `billing_interval` if annual billing is ever planned. The design has a feature list and a "/year" plan.
- **App today:** builds the feature lines from the plan's allowances.

#### BILLING-9 · minor · Fees list
✅ Fixed: `GET /billing/fees` is paged (`page`, `pageSize`, `pagination` beside `data`) and filters before paging by `state` and `from_date`/`to_date` (inclusive). Each row carries `payment_id`.
- **Endpoint:** `GET /billing/fees`.
- **Needed:** pagination, filters (`state`, date range), and `payment_id` on each row to link to the receipt.

#### BILLING-10 · minor · Invoice lines
✅ Fixed: every line carries `state` (`PENDING`/`REFUNDED` on fee lines), `fee_charge_id`, `payment_reference` and `created_at`, all `null` on plan and add-on lines. The preview carries `next_charge_date`: `trial_end` during a trial, otherwise `period_end`, `null` when cancelling or when nothing is collected.
- **Endpoint:** `GET /billing/invoice`.
- **Needed:** a machine-readable `state`, `fee_charge_id`, `payment_reference` and `created_at` on lines, and a `next_charge_date` on the preview. `period_end` is documented as "when the allowance resets", not "when the card is billed".
- **App today:** infers "refunded" from `total == 0`.

#### BILLING-11 · minor · Codes on 402 and 403
✅ Fixed: every 402 carries `code: "plan_limit"` and `limit` (`BANKS`, `SEATS`, `CHECKS`, or `null`). A 403 for a missing role capability carries `code: "role_forbidden"` and `capability` (e.g. `manage_billing`).
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
- **🟡 Partly fixed** (with DASH-3): native clients now send `Authorization: Bearer …` on the handshake, so the mobile app's token never appears in a URL. Browsers still use `?token=`, because they cannot set handshake headers; the single-use ticket is still open for them.
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
