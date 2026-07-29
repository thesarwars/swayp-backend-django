"""Acting account and capability enforcement (E10-S1).

Two things every caller outside ``apps/teams`` needs:

* ``acting_account(request)`` — whose account this request operates on. For a
  solo user that is themselves; for someone who accepted an invitation it is
  the account that invited them. This is the seam the rest of the codebase
  moves onto as team-wide data visibility lands, so the resolution lives here
  rather than being re-derived per view.

* ``RequiresCapability`` — a DRF permission that refuses an action the
  caller's role does not hold. It answers **403**, not 402: this is a
  permissions problem, and dressing it as a plan limit would send the user to
  the pricing page for something no upgrade can fix.
"""

from rest_framework.permissions import BasePermission

from apps.teams.permissions import role_can
from apps.teams.services.team_service import TeamService


def acting_account(request):
    """The account this request acts on.

    A member who accepted an invitation acts on the inviting account. Falling
    back to ``request.user`` keeps every solo user — which is everyone until
    they invite someone — behaving exactly as before.
    """
    membership = TeamService().membership_for(request.user)

    if membership is not None:
        return membership.account

    return request.user


def acting_role(request):
    return TeamService().role_for(request.user, acting_account(request))


class RequiresCapability(BasePermission):
    """Refuse an action the caller's role does not grant.

    The view names what it needs::

        class PaymentConfirmAPIView(BaseAPIView):
            required_capability = SEND_MONEY

    A view that names nothing is unrestricted, so this is safe to add to the
    default permission list without auditing every endpoint at once.
    """

    message = "Your role does not allow this action."

    def has_permission(self, request, view):
        capability = getattr(view, "required_capability", None)

        if capability is None:
            return True

        if not request.user or not request.user.is_authenticated:
            # IsAuthenticated owns this case; returning True defers to it so
            # an anonymous caller gets 401 rather than a confusing 403.
            return True

        role = acting_role(request)

        if role is None:
            # No membership row at all means a solo account acting on itself,
            # which ensure_owner_seat would have made OWNER. Treat an
            # unresolvable role as denied rather than assuming ownership.
            return False

        return role_can(role, capability)
