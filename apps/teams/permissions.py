"""What each role may do (E10-S1).

The BRD does not specify a permissions matrix, so this is a product decision
made explicitly rather than left implicit in scattered `if role ==` checks:

* **MEMBER** — read everything, create and edit bills and vendors, but no
  money out and no account changes. A member can prepare the work; approving
  it costs a higher role.
* **ADMIN** — everything operational, including sending money and managing the
  team. Not billing: changing the plan changes what the owner is charged.
* **OWNER** — everything.

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
SEND_MONEY = "send_money"
MANAGE_BANKS = "manage_banks"
MANAGE_TEAM = "manage_team"
MANAGE_ENTITIES = "manage_entities"
MANAGE_BILLING = "manage_billing"

ALL_CAPABILITIES = (
    VIEW,
    MANAGE_BILLS,
    MANAGE_VENDORS,
    SEND_MONEY,
    MANAGE_BANKS,
    MANAGE_TEAM,
    MANAGE_ENTITIES,
    MANAGE_BILLING,
)

ROLE_CAPABILITIES = {
    TeamRole.OWNER: set(ALL_CAPABILITIES),
    TeamRole.ADMIN: {
        VIEW,
        MANAGE_BILLS,
        MANAGE_VENDORS,
        SEND_MONEY,
        MANAGE_BANKS,
        MANAGE_TEAM,
        MANAGE_ENTITIES,
    },
    TeamRole.MEMBER: {
        VIEW,
        MANAGE_BILLS,
        MANAGE_VENDORS,
    },
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
