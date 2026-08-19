# E10 — Teams & Entities

**Goal:** the account-structure the plans reference (BRD §6.2) — team members with per-plan seat limits, and (Enterprise) multi-entity accounts with approval workflows + ERP sync.
**Release:** team seats in **R2**; Enterprise features **later** · **Blocked by:** E1, E2 · **New app:** `apps/teams` (or extend `apps/users`) · **Screens:** none provided (team/settings UI missing — PRD §10-Q8)

> Seat/entity limits are enforced against the plan (E9). Founding = 3 seats / 1 entity, Standard = 10 seats, Enterprise = unlimited seats / 3 entities included then +$79/entity.

---

## E10-S1 · TeamMember + seat enforcement

**As an** account owner **I add** team members **so that** my team can use Swayp, up to my plan's seat limit.

**ORM (`apps/teams/models/team_member.py`):**
```python
class TeamMember(BaseModel):
    account = FK("users.User", CASCADE, related_name="team_members")   # account owner / org
    user    = FK("users.User", CASCADE, related_name="memberships", null=True)  # null until invite accepted
    email   = EmailField()                                              # invited address
    role    = CharField(choices=[OWNER, ADMIN, MEMBER], default=MEMBER)
    status  = CharField(choices=[INVITED, ACTIVE, REMOVED], default=INVITED)
    class Meta:
        db_table = "team_members"
        constraints = [UniqueConstraint(fields=["account","email"], name="uniq_member_per_account")]
```
**Behavior:** adding a member checks the plan `seat_limit` via E9-S2 (capacity counter) → **402/403 "seat limit reached — upgrade plan"** when full. Enterprise = no cap.
**AC:** [ ] seat add blocked at plan limit (Founding 3 / Standard 10); [ ] Enterprise unlimited; [ ] owner seat counts toward the limit (confirm) ; [ ] removing a member frees a seat

## E10-S2 · Invitations

**As an** owner **I invite** by email; **as an** invitee **I accept** and join the account.

**API:** `POST teams/invite` (email, role) → INVITED row + email (E8 notify); `POST teams/invite/accept` (token) → links `user`, status ACTIVE, consumes a seat. Reuses the OTP/email delivery (E2).
**AC:** [ ] invite email sent (mock in CI); [ ] accept links the user + flips seat counter; [ ] expired/duplicate invite handled; [ ] can't accept past seat limit (edge: owner downgraded after invite)

## E10-S3 · Entity (multi-entity, Enterprise)

**As an** Enterprise admin **I manage** multiple entities under one account **so that** each entity's bills/vendors/payments are scoped.

**ORM (`apps/teams/models/entity.py`):**
```python
class Entity(BaseModel):
    account   = FK("users.User", CASCADE, related_name="entities")
    legal_name = CharField(max_length=150)
    ein        = CharField(max_length=20, blank=True)
    status     = CharField(choices=[ACTIVE, ARCHIVED], default=ACTIVE)
    class Meta: db_table = "entities"
```
**Scoping:** when entities are enabled, `Vendor`/`Bill`/`Payment` gain a nullable `entity` FK (single-entity accounts leave it null). Entity count > `included_entities` (3) drives the E9-S5 extra-entity add-on.
**AC:** [ ] entity CRUD (Enterprise-gated); [ ] data scoping filter applied when entities exist; [ ] entity count feeds billing add-on; [ ] non-Enterprise accounts can't create a 2nd entity

## E10-S4 · Approval workflows + ERP sync *(later phase — deferred)*

**As an** Enterprise admin **I require** approvals before payments and **sync** to my ERP (NetSuite / Sage Intacct / custom API).

⟳ **Deferred beyond R4 — confirm scope (PRD §10-Q10).** Placeholder for: an approval step gating E6 payment confirm for flagged bills/amounts; and an ERP export/sync adapter behind an integration interface. Billed as E9-S5 add-ons ($99 workflow / $149 ERP).
**AC (when scheduled):** [ ] approval gate blocks E6 confirm until approved; [ ] ERP sync behind a provider interface with a mock; [ ] both toggled by the E9 add-on being active

---

## Cross-epic hooks
- **E9** owns seat/entity **limits + billing**; this epic enforces them at add-time.
- **E6** payment confirm consults the (later) approval workflow when enabled.
- **E2** provides the invite email/OTP plumbing.
- Data models (`Vendor`/`Bill`/`Payment`) gain a nullable `entity` FK only once multi-entity ships — no-op for single-entity accounts.

## Open questions (teams)
- Does the owner seat count against the plan limit, or is it "owner + N members"? (affects Founding 3/Standard 10 math)
- Per-role permissions matrix (OWNER/ADMIN/MEMBER) — not in the BRD; needs product input.
- Multi-entity data isolation depth (separate funding sources per entity? separate Plaid connections?) — confirm for Enterprise.
