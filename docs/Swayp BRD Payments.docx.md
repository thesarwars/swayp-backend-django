

| SWAYP INC. *bills, swayped away.* BUSINESS REQUIREMENTS DOCUMENT |
| :---: |

Payments & Bank Connectivity — Build Specification for Engineering

**Prepared by: Latascha Welly, CEO  ·  Swayp Inc.**

Version 1.0  ·  July 2026

Audience: Engineering Team  ·  Classification: Internal

# **Document Control**

| Version | Date | Summary of change |
| :---- | :---- | :---- |
| 1.0 | July 2026 | Initial BRD: two-tier payment architecture (Stripe \+ Moov), Plaid bank connectivity, non-custodial position, same-day ACH, and all resolved decisions consolidated for build. |
| 1.1 | July 2026 | Added physical check payments (Lob/PostGrid) to scope. Finalized full commercial pricing structure: subscription plans, per-transaction fees, and Enterprise base \+ add-on rate card. |

*This document consolidates all payments-architecture decisions into a single build specification. It supersedes prior informal guidance and the point-by-point Architecture Decision Response memo — engineering should build against this document.*

# **1\.  Purpose & Scope**

This BRD defines what Engineering must build to support bill payment inside Swayp. It covers bank connectivity, payment execution for two vendor types, currency handling, and the compliance boundaries that keep Swayp non-custodial. It does not repeat UI/screen specifications already covered in the Functional Design Document (FDD) — it defines the underlying payments architecture those screens depend on.

## **1.1  In scope**

**✓**  Bank account connectivity (Plaid)

**✓**  Payment execution for vendors with a configured payment link (Stripe)

**✓**  Payment execution for vendors paid via bank transfer with routing/account numbers (Moov)

**✓**  Standard and same-day delivery speed options for bank transfers

**✓**  Physical check printing and mailing, standard and expedited (Lob or PostGrid)

**✓**  Currency and data-handling standards

## **1.2  Out of scope for this release**

**✕**  Invoice OCR / auto-import (pending a separate CEO decision — see Section 6\)

**✕**  SMS notifications (email only for this release)

**✕**  Any integration with BILL.com or similar all-in-one AP/AR platforms (competitive conflict — rejected, see Section 7\)

# **2\.  Business Objective**

| THE REQUIREMENT IN ONE SENTENCE Swayp must be able to pay any US vendor — whether or not that vendor has a payment account with our processor — without Swayp ever holding, storing, or transmitting customer funds. |
| :---- |

**Two vendor situations exist, and each requires a different execution path:**

| Vendor situation | Business requirement |
| :---- | :---- |
| Vendor has a configured payment account with our processor (e.g. large recognized businesses) | Payment must complete with the fewest possible steps and the lowest possible cost. |
| Vendor only provided a bank routing and account number (e.g. a landlord, local contractor, small utility) | Payment must still be possible, fully inside the Swayp experience, without asking the customer to leave the app or manually wire funds elsewhere. |

Both situations must be resolved without Swayp becoming a licensed money transmitter, without Swayp storing sensitive banking data, and without introducing dependency on any company that competes for the same customer relationship Swayp is building.

# **3\.  Functional Requirements**

## **3.1  Bank Connectivity**

| Requirement | Detail |
| :---- | :---- |
| Connect a business bank account | The customer must be able to securely link their bank account during sign-up. Swayp must never see or store their online banking login credentials. |
| Read account balance | Swayp must have real-time visibility into the connected account’s balance to power Flo’s Cash Context feature. |
| Read transaction history | Swayp must be able to scan up to 12 months of transaction history to automatically detect recurring bills. |
| One connection, two purposes | The same bank connection a customer makes at sign-up must also serve as instant proof of ownership when Swayp later needs to move money from that account — the customer should never be asked to verify their own bank a second time. |

## **3.2  Paying Vendors With a Configured Payment Account**

| Requirement | Detail |
| :---- | :---- |
| One-click payment experience | When a customer pays a vendor who is already set up to receive payments through our processor, the flow must be as fast as possible: confirm, send, done. |
| Payment confirmation | Swayp must automatically know the moment a payment succeeds or fails — no manual status checking. |
| No sensitive data stored | Swayp must never store or process the customer’s card or bank credentials for this payment type. That data belongs entirely to our processor. |

## **3.3  Paying Vendors With Only a Bank Routing & Account Number**

| Requirement | Detail |
| :---- | :---- |
| Collect vendor bank details once | The customer enters the vendor’s routing and account number one time when adding the vendor. |
| Verify the vendor’s bank account belongs to them | Before the first payment can be sent, the vendor’s bank account must be verified as real and correctly entered. This protects the customer from sending money to the wrong place due to a typo. |
| Execute the transfer | Once verified, the customer can pay this vendor the same way they pay any other vendor — through the standard Swayp payment experience, with no extra steps after the first-time verification. |
| Standard delivery, included at no charge | Funds normally arrive at the vendor’s bank within 1–3 business days. This is the default option and carries no additional fee. |
| Same-day delivery, optional paid upgrade | A customer may choose to have funds arrive the same business day for an additional flat fee of $4.99, provided the request is made before that day’s bank processing cutoff. If the cutoff has passed, the system must not offer same-day delivery for that day and must not charge the fee. |
| Track payment outcome | Swayp must automatically know when a transfer completes, fails, or — in rare cases — is reversed by the receiving bank days after initially appearing successful. Any reversal must update the bill status and notify the customer. |

## **3.4  Data Handling Requirements**

| 🔒 REQUIRED  Sensitive banking data must never be stored in Swayp’s own systems Full bank routing and account numbers must be transmitted securely to the relevant payment provider and stored on that provider’s systems — never inside Swayp’s own database, logs, or backups. Swayp may only retain a masked display value (e.g. ••••4821) and a reference identifier, so customers can recognize their accounts without any raw financial data being exposed. |
| :---- |

## **3.5  Currency Requirement**

| CRITICAL 🔴  Swayp operates in US Dollars only Every bill, payment, receipt, and calculation in the system must be in USD. This is a hard constraint with no exceptions and must be enforced at the data layer, not just the user interface. |
| :---- |

# **4\.  Compliance & Risk Requirements**

These are business requirements, not suggestions. Each protects Swayp’s legal and financial position.

| Requirement | Why it matters |
| :---- | :---- |
| Swayp must never hold, store, or transmit customer funds at any point | This is the foundation of Swayp’s non-custodial legal position. If violated, Swayp could be legally classified as a money transmitter, requiring state-by-state licensing that would take months and significant legal cost to obtain. |
| Every payment must be traceable to a specific, licensed payment provider | Regulatory questions about how money moved must always have a clear answer: a named, licensed provider executed it — not Swayp. |
| Identity and business verification for vendors and payment providers is the provider’s responsibility, not Swayp’s | Swayp performs only a lightweight verification of its own paying customers at sign-up. It does not independently verify vendors or run anti-fraud/sanctions screening — the payment providers already carry that obligation as licensed financial institutions. |
| A written legal opinion is required before the bank-transfer payment path goes live in production | Counsel must confirm in writing that the specific transfer model used for bank-routing-number vendors does not create custody exposure under Texas law and any other state Swayp operates in. This is a prerequisite for launch of that feature, not a formality. |

## **4.1  Explicitly rejected approaches**

The following were considered and rejected. Engineering should not revisit them without a new business decision:

**✕**  Holding customer funds in a Swayp-controlled balance between the debit and credit side of a payment, even briefly.

**✕**  Using a payment partner whose product roadmap directly overlaps with Swayp’s own core offering (vendor management, bill pay, AP automation) — see Section 7\.

**✕**  Defaulting to any currency other than USD.

# **5\.  Approved Providers**

The following providers are approved for the roles listed. No other provider should be introduced into the payments or bank-connectivity flow without a new business decision.

| Provider | Role | Why approved |
| :---- | :---- | :---- |
| Plaid | Bank account connection, balance, transaction history, recurring bill detection | Neutral financial data utility. Does not compete with Swayp’s product. |
| Stripe | Payment execution for vendors with a configured payment account | Licensed payment processor. Does not compete with Swayp’s product. |
| Moov | Payment execution for vendors paid via bank routing/account number | Licensed money-services provider built specifically for platforms like Swayp. Does not compete with Swayp’s product. |
| Lob or PostGrid | Physical check printing and USPS mailing for vendors who only accept paper checks | Print/mail infrastructure provider. Does not move money and does not compete with Swayp’s product. |

## **5.1  Provider selection principle**

| PRINCIPLE  Any future provider must pass this test before approval Does this provider’s core business model depend on being neutral infrastructure, or does it depend on owning the same day-to-day customer relationship Swayp is trying to own? If the answer is the latter, the provider is a competitor, not infrastructure, and must be rejected regardless of how convenient the integration appears. |
| :---- |

# **6\.  Open Business Decisions**

The following require a decision from the CEO before Engineering can scope the related work. None of these block the core payment architecture described above.

| \# | Decision needed | Status |
| :---- | :---- | :---- |
| 1 | Include automatic invoice scanning / auto-import in this release, or defer. | Pending |
| 2 | Confirm whether Flo’s advisory features require explicit customer opt-in consent under state privacy law. | Pending — legal review requested |

## **6.1  Time-sensitive action items**

| Action | Why it’s time-sensitive |
| :---- | :---- |
| Submit the platform application to the bank-transfer provider | Approval for production access can take 2–4 weeks and is on the critical path for launching bank-routing-number vendor payments. |
| Engage the fintech attorney for the required written opinion | This sign-off is a prerequisite for production launch of the bank-transfer payment path and typically takes 1–2 weeks once engaged. |

## **6.2  Commercial Pricing Structure — RESOLVED**

| RESOLVED ✓  Physical check payments are approved for this release, with pricing finalized. Physical check payments (for vendors who only accept mailed checks) are in scope for this release. Pricing and plan allowances are finalized below. |
| :---- |

**Subscription plans**

| Plan | Price | Positioning |
| :---- | :---- | :---- |
| Founding | $49/mo flat, price locked for the first 500 customers | Up to 3 team members, 1 connected bank account, unlimited bills/vendors, full access to Flo, 2 checks/mo included |
| Standard | $99/mo flat | Up to 10 team members, unlimited connected bank accounts, 1099 reporting, priority support, 5 checks/mo included |
| Enterprise | Custom, quoted from a fixed base \+ add-on rate card | Multi-entity, approval workflows, advanced ERP sync, unlimited team members, dedicated account manager |

**Per-transaction pricing**

| Item | Price |
| :---- | :---- |
| Standard ACH transfer (1–3 business days) | Free, unlimited, on all plans |
| Same-day ACH transfer | $4.99 per payment, opt-in, unavailable and unbilled after the daily bank cutoff |
| Standard physical check (5–7 business days) | 2 free/mo on Founding, 5 free/mo on Standard, then $2.99 each |
| Expedited physical check (1–2 business days) | $8.99 per check, all plans |

**Enterprise base \+ add-on rate card (sales starting point)**

Enterprise remains “custom pricing” on the public site, but Sales must quote from this fixed starting structure rather than improvising a number. The full negotiation guardrails for this tier are maintained separately in the Swayp Enterprise Rate Card for the Sales/CS team.

| Component | Starting price |
| :---- | :---- |
| Platform base fee | $299/mo — includes everything in Standard, unlimited users, dedicated account manager, and up to 3 entities |
| Each additional entity beyond 3 | \+$79/mo per entity |
| Approval workflow engine | \+$99/mo flat |
| Advanced ERP sync (NetSuite, Sage Intacct, custom API) | \+$149/mo |
| Custom SLA / guaranteed response times | \+$199/mo |

**Engineering impact of the pricing structure**

**✓**  Billing system must track per-plan check and same-day ACH allowances, and correctly bill overages at $2.99/check and $4.99/same-day transfer.

**✓**  Same-day ACH and expedited check fees must be refunded automatically if Swayp fails to meet the delivery guarantee (see Sections 3.3 and this section).

**✓**  The billing system must support add-on line items for Enterprise accounts (entity count, workflow engine, ERP sync, SLA) as separately trackable, invoiceable components — not a single opaque “custom” charge.

**✓**  Bank-holiday and business-day calendar logic (already required for same-day ACH) also governs expedited check delivery promises.

# **7\.  Vendor Exclusion on Record**

| DECISION RECORDED ✕  BILL.com evaluated and rejected as an infrastructure provider BILL.com’s API was evaluated as a possible source for vendor search, vendor management, or payment workflows. It was rejected because BILL.com’s core business is the same product Swayp is building — not neutral infrastructure. Relying on it would make Swayp’s core product permanently dependent on a direct competitor’s continued willingness to expose those capabilities. Exploratory conversations with BILL.com for market research purposes only (e.g. understanding vendor onboarding patterns) remain acceptable, provided no data-sharing agreement, pilot, or integration commitment results from them. |
| :---- |

*This exclusion applies to any company whose core business is bill management, AP/AR automation, or vendor payment workflows for small and mid-size businesses — not only BILL.com by name.*

# **8\.  Summary for Engineering**

| THE BUILD IN ONE PARAGRAPH Connect bank accounts through Plaid. Pay vendors with a configured payment account through Stripe. Pay all other vendors via bank transfer through Moov, with a free standard-speed option and a paid same-day option. Print and mail physical checks through Lob or PostGrid, with a free monthly allowance per plan and a paid expedited option. Never store raw banking details. Never let money touch Swayp’s own systems. Keep USD as the only currency. Track every plan allowance and overage accurately for billing. Do not integrate BILL.com or any similar competing platform. |
| :---- |

**Acceptance criteria for this release:**

**✓**  A customer can connect their bank account once and never be asked to re-verify it for payment purposes.

**✓**  A customer can pay a vendor with a configured payment account in one confirmed action.

**✓**  A customer can add a new vendor using only a routing and account number, complete a one-time verification, and then pay that vendor the same way as any other vendor.

**✓**  A customer can choose standard (free) or same-day ($4.99) delivery for any bank-transfer payment, with same-day unavailable and unbilled after the daily cutoff.

**✓**  A customer can send a physical check to a vendor, with the correct monthly free allowance applied by plan (2 for Founding, 5 for Standard) before $2.99 overage billing begins, and can optionally pay $8.99 for expedited delivery.

**✓**  No screen, log, or database table in Swayp ever displays or stores an unmasked bank routing or account number.

**✓**  All monetary values in the system are in USD with no other currency accepted.

**Approved by:**

**Latascha Welly — CEO, Swayp Inc.**

July 2026

*Engineering should treat this document as the authoritative build reference for payments and bank connectivity. Questions or proposed deviations should be raised with the CEO before implementation.*