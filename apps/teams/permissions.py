"""What each role may do (E10-S1, Teams roles).

The BRD does not specify a permissions matrix, so this is a product decision
made explicitly rather than left implicit in scattered `if role ==` checks:

* **VIEWER** — read everything, change nothing.
* **MEMBER** (shown as *Accountant*) — prepares the work: bills, vendors and
  scheduling payments. Nothing it does moves money; a scheduled payment waits
  for someone who may approve it.
* **APPROVER** — everything an Accountant does, plus approving and sending
  payments and turning autopay on (a standing authorization is an approval
  in advance). No banks, no team.
* **ADMIN** — everything operational, including banks, the team and changing
  where an existing vendor is paid. Not billing or account settings: changing
  the plan changes what the owner is charged.
* **OWNER** — everything.

Changing an existing vendor's payment details is its own capability because
redirecting a known payee's money is the classic payment fraud: an Accountant
may add a vendor with its first payment method, but not repoint one.

Fail-closed in both directions: an unknown capability is denied, and an
unknown role is denied. Adding a capability without granting it to anyone
means it is refused, which is the safe way round.

Reading a permission is deliberately one function so a UI can ask the same
question the API enforces (see ``capabilities_for``), rather than
reimplementing the matrix in the client and drifting.
"""

from apps.teams.models import TeamRole

# --- capabilities ---------------------------------------------------------
# Named for the action, not the endpoint, so a route can move without the
# permission moving with it.

VIEW = "view"
MANAGE_BILLS = "manage_bills"
MANAGE_VENDORS = "manage_vendors"
MANAGE_VENDOR_PAYMENT_DETAILS = "manage_vendor_payment_details"
SCHEDULE_PAYMENTS = "schedule_payments"
SEND_MONEY = "send_money"
MANAGE_BANKS = "manage_banks"
MANAGE_TEAM = "manage_team"
MANAGE_ENTITIES = "manage_entities"
MANAGE_BILLING = "manage_billing"
MANAGE_ACCOUNT = "manage_account"

ALL_CAPABILITIES = (
    VIEW,
    MANAGE_BILLS,
    MANAGE_VENDORS,
    MANAGE_VENDOR_PAYMENT_DETAILS,
    SCHEDULE_PAYMENTS,
    SEND_MONEY,
    MANAGE_BANKS,
    MANAGE_TEAM,
    MANAGE_ENTITIES,
    MANAGE_BILLING,
    MANAGE_ACCOUNT,
)

_PREPARE = {VIEW, MANAGE_BILLS, MANAGE_VENDORS, SCHEDULE_PAYMENTS}

ROLE_CAPABILITIES = {
    TeamRole.OWNER: set(ALL_CAPABILITIES),
    TeamRole.ADMIN: set(ALL_CAPABILITIES) - {MANAGE_BILLING, MANAGE_ACCOUNT},
    TeamRole.APPROVER: _PREPARE | {SEND_MONEY},
    TeamRole.MEMBER: set(_PREPARE),
    TeamRole.VIEWER: {VIEW},
}


def role_can(role, capability):
    """Does this role hold this capability?

    Unknown role or unknown capability is False. Both are programming errors,
    and denying is the failure that does not move money.
    """
    if capability not in ALL_CAPABILITIES:
        return False

    return capability in ROLE_CAPABILITIES.get(role, set())


def capabilities_for(role):
    """Every capability a role holds, sorted, for the client to render with.

    Returned so a UI can hide what it must not offer. It is not the
    enforcement — the API checks every action itself, because a hidden button
    is not a permission.
    """
    return sorted(ROLE_CAPABILITIES.get(role, set()))
