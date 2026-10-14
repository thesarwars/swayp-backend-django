# Swayp API: backend gap report

**Tested:** 14 Oct 2026 against `https://swayp.jumatechs.xyz` (development API)
**Contract:** OpenAPI schema at `/api/schema/` (135 operations)
**Companion file:** `FRONTEND_GAPS.md`

## How this was tested

- Every list and summary `GET` was called with a real owner token. Detail endpoints were called with the account's only vendor and with unknown IDs.
- Write endpoints were called only with empty or invalid bodies, to read the validation errors, or as read-only previews: routing validation, QR decode, bank-link token and socket ticket. **Nothing was created, changed or deleted.**
- The test account is an owner on the Founding plan (`account_type: INDIVIDUAL`). It has 1 vendor, 0 bills, 0 payments and no connected bank. Bill and payment detail flows were therefore checked only against the schema and with unknown IDs.
- Server time per request is about 0.1 s. The roughly 0.9 s seen per call came from the tester's network round-trip and TLS setup, not from the backend.

**Priority:** **P0** = blocks a core flow or is a security risk · **P1** = wrong or inconsistent behaviour that clients must work around · **P2** = cleanup or docs

## Summary

| # | Issue | Priority |
|---|---|---|
| S1 | Payment status endpoints (`/successful`, `/processing`, `/failed`) accept normal user tokens; the staff check doesn't run before the lookup | P0 |
| S2 | CORS accepts every origin, with credentials | P0 before production |
| B9 | Vendor bank details can't be sent, and any `provider_token` string is accepted | P0 |
| S4 | No minimum password length (a 4-character password passes validation) | P1 |
| C8 | Error `code` is `validation_failed` for every refusal, so clients match message text | P1 |
| B1 | `GET /banking/institutions` returns 500 when `search` is missing | P1 |
| B4 | The user's display name differs across 4 endpoints | P1 |
| B6 | Notification preferences say push is enabled; the docs say it can't be | P1 |
| C1 | Vendor endpoints skip the `{success, message, data}` envelope | P1 |
| C2 | Pagination and several payloads send every key twice (camelCase and snake_case) | P1 |
| C3 | Query params use three naming styles; `page_size` is silently ignored | P1 |
| C5 | Browsers can't read `Retry-After` or `Content-Disposition` | P1 |
| E1 | Stripe isn't configured on dev, so the card and subscription flow can't be tested | P1 |
| M | Missing endpoints: public plans, change password, profile photo, approvals and ERP add-ons, and more (§4) | P1–P2 |
| D | 16 operation descriptions are leaked internal docstrings; webhooks are documented with the wrong auth (§6) | P2 |

---

## 1. Security and permissions

### S1: Clients can reach payment status changes (P0)

✅ **Already safe; now hidden.** All three routes are `IsAdminUser`: a customer gets **403** before any lookup, for their own payment and for unknown IDs. A 404 means the token belongs to a staff account. They're now excluded from the client schema, and a test pins the 403.

`PATCH /api/v1/payments/{id}/successful`, `/processing` and `/failed` are part of the public client API. Only `/failed` is documented as "Staff only."

- With a normal owner token, all three return `404 "Payment not found."` for an unknown ID instead of `403`, so no permission check runs before the object lookup.
- If a user can call `/successful` on their own payment, they can mark a payment as delivered when no money moved.
- Not tried against a real payment, because the account has none.

**Fix:** limit all three to staff or the processor callback (`IsAdminUser` or service auth), check permissions before the object lookup, and remove them from the client schema.

### S2: CORS allows every origin with credentials (P0 before production)

✅ **Fixed.** CORS is an allow-list in every environment. Production had the same bug: it set a list but inherited `CORS_ALLOW_ALL_ORIGINS = True`, which corsheaders checks first. With no `CORS_ALLOWED_ORIGINS` set, the default is `localhost:3000`, `127.0.0.1:3000`, `getswayp.com` and `www.getswayp.com`.

```
Origin: https://swayp.example.com
→ Access-Control-Allow-Origin: https://swayp.example.com
→ Access-Control-Allow-Credentials: true
```

Every origin gets this answer. Bearer tokens limit the damage. But if `SessionAuthentication` is enabled anywhere (browsable API, admin), any website can read API responses as a signed-in staff user.

**Fix:** set `CORS_ALLOWED_ORIGINS` to the real frontends (`http://localhost:3000` on dev, plus the production domain) and turn off allow-all.

### S3: Harden before production (P2)

- `/` redirects to a public Swagger UI at `/api/docs`. `/api/schema/` is public, and Django admin is at the default `/admin/`.
- The mock processor webhook is deployed at `/webhooks/mock` and `/api/v1/webhooks/mock`. It checks signatures, but it should be disabled in production settings.
- There is no `Strict-Transport-Security` header, and the `Server` header reveals `nginx/1.24.0 (Ubuntu)`.

### S4: The password policy has no minimum length (P1)

**Won't change (product decision).** No length minimum. The rules stay as documented: character classes, and no reuse of the previous password.

`RegisterRequest.password` has `minLength: 1`. `POST /auth/register {"email": "not-an-email", "password": "Ab1@"}` returned an error only for `email`, so a 4-character password passes field validation. The frontend notes say this is intentional ("no length minimum"). For a finance product, require at least 12 characters and document the rule in the schema.

### S5: The web app has to keep a 30-day refresh token in localStorage (P2)

Auth is bearer-only. The web client therefore stores a rotating 30-day refresh token where any XSS can read it, and it can't guard routes on the server. Consider an httpOnly, `SameSite` cookie option for refreshing tokens on the web.

---

## 2. Bugs

### B1: `GET /banking/institutions` returns 500 without a search term (P1)

✅ **Fixed.** A missing or blank `search` is never a 500. On Plaid it returns `200` with `data: []` without calling Plaid. The mock provider still returns its default set.

| Request | Response |
|---|---|
| `GET /api/v1/banking/institutions` | `500 {"success":false,"message":"Internal server error.","code":"server_error"}` |
| `GET /api/v1/banking/institutions?search=` | `500`, same body |
| `GET /api/v1/banking/institutions?search=chase` | `200` with results |

**Fix:** return `400 validation_failed` on `search`, or return an empty or "popular" list.

### B2: Payment methods of an unknown vendor return 200 (P2)

✅ **Fixed.** An unknown, foreign or deleted vendor returns `404 "Vendor not found."` here too.

`GET /vendors/{unknown}/payment-methods` returns `200 {"items": [], …}`, but `GET /vendors/{unknown}` returns 404. Both should return 404.

### B3: Invalid filter values are ignored instead of rejected (P1)

✅ **Fixed.** These now return `400 validation_failed` naming the field: an unknown `rail`, `status` or non-UUID `category` on `/vendors` and `/vendors/summary`; an unknown `status`, even inside a comma list, or a malformed `date_from`/`date_to` on `/bills/occurrences`; and an unknown `status` on `/payments/history`.

- `GET /vendors?rail=BOGUS` drops the filter and returns **every** vendor.
- `GET /bills/occurrences?status=BOGUS` and `GET /payments/history?status=BOGUS` return 200.
- `GET /dashboard/home?tab=BOGUS` and `GET /reports?date_from=bad` correctly return 400. Every choice filter should validate the same way.

### B4: The user's display name differs per endpoint (P1)

✅ **Fixed.** Every endpoint uses one helper: the profile's `full_name`, then first plus last name, then `""`. It never uses the email; `teams/members` returns `null` instead. `greeting.name` is the first word of that name, for the **viewer** rather than the account owner. A profile created without a name no longer stores the email, and migration `users/0007` clears the ones that did.

For the same account:

| Endpoint → field | Value |
|---|---|
| `GET /users/profile` → `full_name` | the account's email address |
| `GET /dashboard/profile-summary` → `fullName` | `""` |
| `GET /dashboard/home` → `greeting.name` | `""` |
| `GET /teams/members` → `name` | `null` |

**Fix:** derive the display name from a single field, and don't store the email as `full_name`.

### B5: The greeting uses the server's time zone (P2)

✅ **Fixed.** `GET /dashboard/profile-summary?tz=Asia/Dhaka` takes the viewer's IANA zone. On the web, send `Intl.DateTimeFormat().resolvedOptions().timeZone`. Without `tz`, the greeting uses US Eastern; an unknown zone returns 400 on `tz`.

`/dashboard/profile-summary` returned "Good Night" at 06:10 UTC, which was midday for the tester (UTC+6). That matches US Eastern time. Use the user's time zone (store it on the profile, or accept a `tz` param), or let the client compute the greeting.

### B6: Notification preferences contradict the docs (P1)

- `GET /notifications/preferences` reports the push channel as `supported: true, enabled: true`.
- The `PATCH` docs say SMS and push "cannot be switched on" in this release.
- The email channel is `enabled: false`, yet every notification type has `email: true`.

**Fix:** report push as `supported: false` until a delivery adapter exists, and document how the channel-level `enabled` relates to the per-type flags.

### B7: Onboarding marks steps complete without any data (P2)

- Step 3 (`payment`) is `complete: true` while `GET /billing/payment-method` returns `null`. Dev has `collects_money: false`.
- Step 1 (`business`) is `complete: true` with every business field `null` (INDIVIDUAL account).

This is probably intended, but the client can't tell "done" from "not applicable." **Fix:** add `not_applicable: true`, or a `reason`, to such steps.

### B8: Timestamp format is inconsistent (P2)

✅ **Fixed.** `expiration` is ISO-8601, e.g. `"2026-10-14T10:15:16Z"`.

`POST /banking/link/token` returns `expiration: "2026-10-14 10:15:16+00:00"`. Every other timestamp is ISO-8601, e.g. `"2026-10-14T06:05:10.328313Z"`.

### B9: Vendor bank details can't be captured, and any processor token is accepted (P0)

- `VendorPaymentMethodCreateRequest`, used by `POST /vendors` and `POST /vendors/{id}/payment-methods`, has no routing or account number fields. It has only `account_last4`, a free-string `provider` (max 20 characters, no enum) and `provider_token`.
- Nothing documents how a client obtains a `provider_token`, and there's no per-`method_type` list of required fields (NETWORK vs ACH vs CHECK).
- A payload with `provider_token: "yerter23424124asdasdad"` (the placeholder the web app sends today) passed field validation. In the same request, only `name`, `category`, `source` and `state` were rejected.

**Fix:** either accept write-only routing and account numbers and tokenize on the server, or document the client-side tokenization flow. In both cases, add a `provider` enum, reject unknown tokens, and document the required fields per method type.

### B10: `category` is "optional" on vendor create but rejected when empty (P2)

The schema marks `category` optional on `POST /vendors`, but `""` returns `"This field may not be null."`, and the list and `PUT` treat it as required. Either make it required in the schema or apply a default ("Other").

---

## 3. Contract consistency

### C1: Vendor endpoints skip the response envelope (P1)

Every other module returns `{success, message, data}`. The vendor endpoints don't:

| Endpoint | Shape today |
|---|---|
| `GET /vendors`, `/vendors/activity`, `/vendors/directory-search`, `/vendors/{id}/payment-methods` | `{items, pagination}` |
| `GET /vendors/{id}` | bare object |
| `GET /vendors/summary` | bare `{total, network, ach, check, check_total}` |
| `POST /vendors/qr/decode` | bare object, while `POST /bills/qr/decode` is wrapped |

Vendor *errors* are wrapped, so clients have to special-case only the successful responses.

**Fix:** wrap vendor responses in the envelope (`data.items` plus `pagination`), or document the exception.

### C2: Every key is sent twice, in camelCase and snake_case (P1)

- Every `pagination` object: `pageSize`/`page_size`, `totalPages`/`total_pages`, `totalItems`/`total_items`, `hasNext`/`has_next`, `hasPrevious`/`has_previous`
- `GET /notifications`: `nextCursor`/`next_cursor`, `unreadCount`/`unread_count`
- `GET /dashboard/profile-summary`: `fullName`/`full_name`, `profilePicture`/`profile_picture`, `unreadNotificationCount`/`unread_notification_count`
- `GET /bill-categories`: `displayOrder`/`display_order`
- `GET /notifications/preferences`: `inApp`/`in_app`, `isDefault`/`is_default`

**Fix:** keep snake_case, which the rest of the API uses, and announce a removal date for the camelCase copies.

### C3: Query parameters use inconsistent names (P1)

- **Page size:** only `pageSize` works. `page_size` is silently ignored, even though responses echo `page_size`.
- **Date ranges:** `fromDate`/`toDate` (payments/history), `date_from`/`date_to` (reports, bills/occurrences), `from_date`/`to_date` (billing/fees).
- **Category:** `category` (vendors, occurrences) vs `categoryId` (payments/history, providers).

**Fix:** choose one style and accept the old names as aliases for a transition period.

### C4: Lists use three pagination styles (P2)

- Most lists: `page` + `pageSize`, answered with a `pagination` object.
- `/billing/invoices`: a cursor (`limit` + `starting_after` → `next_cursor`).
- `/notifications`: both page pagination **and** a cursor (`before` → `nextCursor`).
- `GET /bills` isn't paginated, by design. The docs point list screens to `/bills/occurrences`.

Document which style each list uses, and either drop the second mechanism on notifications or say which one wins.

### C5: Browsers can't read two needed headers (P1)

✅ **Fixed.** `Access-Control-Expose-Headers: Retry-After, Content-Disposition`.

The API sends no `Access-Control-Expose-Headers`, so browser code can't read:

- `Retry-After` on a 429 from `auth/resend-otp` and `users/profile/phone`. The OTP countdown needs it.
- `Content-Disposition` on `GET /reports?export=csv`, and on `payments/{id}/receipt.pdf` once that returns a file. The download's file name comes from it.

**Fix:** `CORS_EXPOSE_HEADERS = ["Retry-After", "Content-Disposition"]`.

### C6: Some errors bypass the envelope or leak framework text (P2)

- Webhooks return `{"detail": "Missing signature header."}`.
- An unknown vendor returns `"No Vendor matches the given query."`, which is Django's default text. Other modules say e.g. `"Bill not found."`.

### C7: Institution logos are bare base64 (P2)

`GET /banking/institutions?search=chase` returns each `logo` as raw base64 PNG, about 8.5 KB for one search. Return a URL, or at least a `data:image/png;base64,` URI.

### C8: Error `code` values are too generic (P1)

Every refusal tested comes back as `code: validation_failed`, including "Invalid email or password." The schema names only `otp_throttled`, `not_authenticated`, `token_not_valid`, `plan_limit`, `forbidden` and `role_forbidden`. These cases have no stable code:

- unverified account and lockout on login
- a code that was already used, and no code pending
- duplicate email
- already subscribed
- declined card

As a result, the web app matches English message text with regexes (`/not verified/`, `/used already/`). **Fix:** add stable codes, e.g. `account_not_verified`, `account_locked`, `otp_used`, `otp_not_pending`, `email_taken`, `already_subscribed`, `card_declined`, and list them per operation.

### C9: Records lack fields the UI needs (P2)

- `BillOccurrenceRow` has only `payment_id`, and its status enum (`UPCOMING`, `DUE`, `OVERDUE`, `SCHEDULED`, `PAID`) can't express "failed" or "processing." Showing a failed payment in the bills list takes one extra call per row. Add `payment_status` (and `can_resolve`).
- `BillDetail.next_occurrence.status` can only be `DUE` or `UPCOMING`, so a bill page can't show "11 days overdue." Expose the oldest open occurrence instead.
- `Payment` and the receipt have only `payment_method_id`, so the "Sent to ACH ••••4821" line can't be built. Add the method type and `account_ref`.
- `BillQRPrefill` has no rail and no `directory_match`, though `VendorQRDecodeResponse` does.
- `BillList` uses `vendor` and `category` for **names**, while create and update use the same keys for **UUIDs**.
- `BillPaymentHistory.payment_status` is a bare string, not the `PaymentStatusEnum`, and `PaymentFailure.failure_detail` is untyped.

---

## 4. Missing endpoints

| Need | Today | Suggestion |
|---|---|---|
| Plans on the public pricing page | `GET /billing/plans` returns 401 without a token | Allow anonymous `GET /billing/plans`, or add a public `/plans` |
| Change password while signed in | Only forgot/reset via OTP exists | `POST /users/password` `{current_password, new_password}` |
| Profile photo | Profile-summary returns `profilePicture`, but nothing can set it | Multipart `PATCH /users/profile` with `profile_picture` |
| Change email; close account | Nothing | `POST /users/email` (plus a verify step); `DELETE /users/account` |
| Approval workflow and ERP sync | Sold as add-ons (`APPROVAL_WORKFLOW`, `ERP_SYNC`) and listed in Enterprise plan features, but there is no API for either | Endpoints to configure and use them, or stop selling them |
| Bill documents | `GET /bills/{id}/invoice` is built from bill data only ("no OCR in v1") | An upload/attach endpoint (OCR later) |
| Vendor bulk import | `source: IMPORT` exists, but there's no import endpoint | `POST /vendors/import` (CSV) |
| Accountant sign-up | Signup offers "Accountant — Free, no card," and login has an Accountant Portal link. The backend has only `INDIVIDUAL`/`BUSINESS` accounts, `OWNER`/`ADMIN`/`MEMBER` roles and no free plan | Decide the product rule; add an account type or role, plus a free plan if needed |
| Microsoft sign-in, Windows Hello | Both are in the design; only Google exists (`POST /auth/login/google`) | Add them, or drop them from the design |
| SMS codes | `ChannelEnum` offers `SMS` on `resend-otp` and `login/phone/request`, and the design says codes are "texted," but SMS answers 501 and phone-login codes are emailed | An SMS adapter, or remove `SMS` from the enum |
| Plan catalogue that matches the design | The API has 3 monthly tiers. The marketing site shows 4 tiers (including Solo) plus yearly prices. Enterprise has a required `monthly_price` and no "contact sales" flag | Agree on the catalogue; add `billing_interval` options and a `quoted`/`contact_sales` flag |
| Fixed option lists for industry, business size, business type | Free strings. The schema example uses the label "Construction," while the web sends slugs | Enums or a `GET /options` endpoint |
| Google sign-up consent | `GoogleLoginRequest` has `terms_accepted` but no `signatory_confirmed` | Add the field |
| Occurrence filters for one bill | `GET /bills/occurrences` has no `bill` filter, no search and no ordering | Add `bill`, `search` and `ordering` |
| Changing a bill's vendor | `PatchedBillUpdateRequest` has no `vendor`, but the edit design offers "Change" | Decide the rule: allow it, or tell design |
| Review screen before saving a bill | `next_due_date` and the summary sentence arrive only after create, so the client re-implements the recurrence math | A `dry_run` flag or a preview endpoint |
| Invoice details | `BillInvoice` has no invoice number, addresses, line items or tax, though the design shows them | Extend it when OCR or uploads land |
| Vendor fields shown in the list | `GET /vendors` shows `business_type` and `logo`, but create and update can't set them, so manual vendors always show "-" | Make them writable, or derive them |
| Fee schedule | Plans expose `free_checks_per_month` but no overage or expedite price, so the UI hard-codes "$1.50/check" | Return fees per rail and per plan (e.g. on `billing/config` or the plan) |
| Contact sales, demo booking, support | Nothing public exists; Flo has only consent, cash-context and balance-projection, all behind auth | A public lead/contact endpoint; a Flo chat endpoint if chat is in scope |
| Analysis page and global search | The sidebar links to Analysis and the header has a search box, but there's no analytics endpoint, no cross-entity search, and no list supports `ordering` | Agree on a design first, then add endpoints |

---

## 5. Dev environment and seed data

- **E1: Stripe isn't configured on dev (P1).** `GET /billing/config` returns `{collects_money: false, publishable_key: ""}`, the subscription's `client_secret` is `""`, and `GET /billing/payment-method` returns `null`. Add Stripe test keys so the setup → SetupIntent → subscription flow can be tested end to end.
- **E2: The biller directory has only stub entries (P2).** Without `q` it returns nothing, and `q=comcast` returns `dir-comcast` "Comcast Business" with `category_id: null`. `GET /providers` is empty. Seed realistic billers with category IDs, and allow browsing without `q`.
- **E3: Category seed data needs cleanup (P2).** There's a "test" category whose icon is the site root URL (`https://swayp.jumatechs.xyz/`) and whose color is `black`. Both "Telephone" and "Phone" exist, most icons are empty, and `display_order` 11 is missing.
- **Working:** Plaid sandbox (`link-sandbox-…`, 24 months of history), the notifications WebSocket (`/ws/notifications/?ticket=` returns 101, or 403 without a ticket), and ABA routing validation.

---

## 6. OpenAPI documentation

- **Leaked internal docstrings.** 16 operation descriptions are internal code comments. For example, `POST /banking/scans` and `GET /bills/occurrences/upcoming` read "Gives a view `self.account(request)`. A mixin rather than a helper import…". Affected:
  - banking: accounts, connections, scans, scan candidates
  - bills: `{id}/details`, occurrences/upcoming
  - payments: confirm, batch cancel
  - teams: entities and members `PATCH`
  - vendors: `{id}` (4 operations)
  - Plaid webhooks (2 operations)
- **Untagged vendor operations.** 9 vendor operations have no summary, and 12 are tagged `api` instead of `Vendors`.
- **Wrong webhook auth.** Webhooks are documented as needing a Bearer JWT, with 401 responses, but they actually verify provider signatures. Each one is also listed twice, under `/webhooks/*` and `/api/v1/webhooks/*`.
- **Stale export note.** The `GET /reports` docs say `export=` is refused with 405, but `export=csv` returns a CSV.
- **Undocumented pagination.** On `GET /bills/occurrences`, `page` and `pageSize` work but aren't documented, and the `status` values aren't listed.
- **No caller rules.** `PATCH /payments/{id}/successful` and `/processing` don't say who may call them (see S1).
- **Trailing slash.** The `GET /dashboard/home` docs use `bills/occurrences/?status=`, with a trailing slash. Both forms work now.
- **Duplicates and gaps.** There are two identical security schemes (`jwtAuth`, `BearerAuth`), and `POST /auth/logout` has no response schema.
- **Hidden query params.** On `GET /vendors/{id}/payment-methods`, `due_date` (which fills in `schedule`) and `amount` are mentioned only in prose, not declared as parameters.
- **Payment lifecycle.** `POST /payments` marks occurrences `SCHEDULED` before confirmation, and payments carry `confirm_by`. It isn't documented:
  - what happens when `confirm_by` passes
  - which status or stage means "sent" for ACH
  - whether `confirm` needs the `authorization_text` byte for byte, and what a replay returns
- **Card and subscribe order.** `SubscribeRequest.payment_method_id` is marked optional, but the prose says it's required "when money is collected." Also undocumented:
  - what `Subscription.client_secret` is for
  - whether a trial needs a card
  - what a second `POST /billing/subscription` returns
  - whether a later card goes to `subscription` or to `billing/payment-method`
- **Onboarding completion rules.** Nothing says which data completes each step: does `business` need `address`, `billing_address` or `poc_name`, and when does `payment` count as done? See B7.
- **Wrong or missing responses.**
  - "No response body" is shown on 200s that do have a body (`reset-password`, `login/phone/request`).
  - No 429 is documented on `login`, `login/phone/request` or `forgot-password`.
  - `VerifyOTPResponse` is one shape for two purposes.
- **Overlapping endpoints.** `GET /providers` and `GET /vendors/directory-search` overlap, with no guidance on which to use.
- **Three biller ID schemes.** Directory hits use `external_id`, providers use `id`/`providerCode`, and the QR `directory_match` returns `{id, provider_name}`. It isn't documented which one is valid as `network_payee_ref`.
- **Undocumented status codes.** Not listed in the schema:
  - 402 on `POST /teams/invite`
  - 402 and 403 on `/teams/entities`
  - 403 for a MEMBER writing vendors, if that's enforced
  
  The maximum `pageSize` on `GET /vendors` isn't documented either.
- **Untyped strings.** `ReportRow.rail` and `ReportRow.status`, `HomeVendorPreview.amount_period`, and `teams/me` `capabilities` are bare strings with no enum.

---

## 7. Questions for the backend team

1. Who is allowed to call `PATCH /payments/{id}/successful|processing|failed`?
2. Is `SessionAuthentication` enabled on the API?
3. Which field is the source of truth for the user's display name?
4. Which casing and which pagination style are canonical, and when will the duplicates be removed?
5. When will Stripe test keys be configured on dev?
6. Should onboarding report steps as "not applicable" for INDIVIDUAL accounts, and when no money is collected?
7. How does a brand-new user accept a team invite? Does `register` or `verify-otp` carry the invite token, and do invitees skip onboarding and billing?
8. Does a trial on the Standard plan need a card, and does the design's "no card needed" hold?
