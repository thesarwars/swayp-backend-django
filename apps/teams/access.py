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

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.teams.permissions import role_can
from apps.teams.services.team_service import TeamService

#: The ``code`` on a 403 for a role that lacks the capability (BILLING-11).
ROLE_FORBIDDEN_CODE = "role_forbidden"


def acting_account(request):
    """The account this request acts on.

    A member who accepted an invitation acts on the inviting account. Falling
    back to ``request.user`` keeps every solo user — which is everyone until
    they invite someone — behaving exactly as before.

    **This, not ``request.user``, is what account-owned data is keyed on.**
    Bills, vendors, payments, banks and the subscription belong to the
    account; using the signed-in user instead gives each teammate a private
    empty copy of the product and, worse, lets them start a second
    subscription of their own.

    Personal things stay on ``request.user``: notifications are addressed to a
    human, and so is everything under ``apps/authentication``.

    Memoised on the request. A view resolves the account several times — once
    per selector call — and without this each one costs a membership query,
    which showed up immediately as the dashboard going from 5 queries to 6.
    The cache is per-request, so it cannot go stale within a request or
    survive beyond it.
    """
    cached = getattr(request, "_swayp_acting_account", None)

    if cached is not None:
        return cached

    membership = TeamService().membership_for(request.user)
    account = membership.account if membership is not None else request.user

    request._swayp_acting_account = account

    return account


class AccountScopedMixin:
    """Gives a view ``self.account(request)``, and enforces its capability.

    A mixin rather than a helper import per view, so the intent is visible in
    the class definition and a view that scopes by account cannot look like
    one that does not.

    Every account-scoped view gets ``RequiresCapability``, so naming
    ``required_capability`` (or ``required_capabilities``) is all a view does
    to be role-checked. Views set ``permission_classes`` in several styles;
    appending here means none of them can drop the check by accident.
    """

    def account(self, request):
        return acting_account(request)

    def get_permissions(self):
        return super().get_permissions() + [RequiresCapability()]


def acting_role(request):
    return TeamService().role_for(request.user, acting_account(request))


def capability_for(view, method):
    """The capability ``method`` on ``view`` needs, or None for none.

    ``required_capabilities`` maps methods to capabilities, for a view whose
    writes need different ones; a method it leaves out needs nothing.
    Otherwise ``required_capability`` covers every method except
    ``safe_methods``.
    """
    per_method = getattr(view, "required_capabilities", None)

    if per_method is not None:
        return per_method.get(method)

    if method in getattr(view, "safe_methods", ()):
        return None

    return getattr(view, "required_capability", None)


def denied_capability(request):
    """The capability a 403 ``role_forbidden`` was for, for the error body."""
    return getattr(request, "_swayp_denied_capability", None)


def has_capability(request, capability):
    """Does the caller's role on the acting account hold ``capability``?

    No membership row at all means a solo account acting on itself, which
    ensure_owner_seat would have made OWNER. An unresolvable role is denied
    rather than assumed to be ownership.
    """
    role = acting_role(request)

    return role is not None and role_can(role, capability)


def require_capability(request, capability):
    """Refuse with 403 ``role_forbidden`` unless the role holds it.

    For a check that depends on the request body rather than the route, such
    as turning autopay on, which only an approver may do.
    """
    if has_capability(request, capability):
        return

    request._swayp_denied_capability = capability

    raise PermissionDenied(
        RequiresCapability.message, code=ROLE_FORBIDDEN_CODE
    )


class RequiresCapability(BasePermission):
    """Refuse an action the caller's role does not grant.

    The view names what it needs::

        class PaymentConfirmAPIView(AccountScopedMixin, BaseAPIView):
            required_capability = SEND_MONEY

    A view that names nothing is unrestricted. ``safe_methods`` exempts reads
    on a view whose writes are restricted::

        required_capability = MANAGE_BILLING
        safe_methods = ("GET",)

    That is the common shape: everyone on the team may see which plan they are
    on, but only the owner may change what the owner is charged. A view whose
    writes need different capabilities maps them instead::

        required_capabilities = {"POST": MANAGE_BANKS}
    """

    message = "Your role does not allow this action."
    code = ROLE_FORBIDDEN_CODE

    def has_permission(self, request, view):
        capability = capability_for(view, request.method)

        if capability is None:
            return True

        if not request.user or not request.user.is_authenticated:
            # IsAuthenticated owns this case; returning True defers to it so
            # an anonymous caller gets 401 rather than a confusing 403.
            return True

        if has_capability(request, capability):
            return True

        request._swayp_denied_capability = capability

        return False
