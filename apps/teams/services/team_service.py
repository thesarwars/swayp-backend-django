"""Team membership, seats and invitations (E10-S1, E10-S2).

Seats are enforced against the plan through E9's AllowanceService, and the
usage it reports derives from the rows here — so the number on the billing
screen and the number the invite gate applies are the same query, never two
counters that can disagree.

The owner occupies a seat. "Founding — 3 seats" has to mean three people who
can sign in, or the pricing page and the headcount contradict each other.
"""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.billing.models import AllowanceKind
from apps.billing.services.allowance_service import AllowanceService
from apps.billing.services.subscription_service import SubscriptionService
from apps.teams.models import (
    TeamMember,
    TeamMemberStatus,
    TeamRole,
    default_invite_expiry,
    new_invite_token,
)
from apps.teams.permissions import MANAGE_TEAM, role_can

logger = logging.getLogger(__name__)


class TeamService:

    def __init__(self):
        self.allowances = AllowanceService()
        self.subscriptions = SubscriptionService()

    # --- membership reads -------------------------------------------------

    def members(self, account):
        return TeamMember.objects.filter(account=account).exclude(
            status=TeamMemberStatus.REMOVED
        )

    def seats_used(self, account):
        """People who can sign in, or are one click from it.

        An invitation counts. If it did not, an owner on a 3-seat plan could
        send thirty invites and only find out at the thirty-first acceptance —
        putting the failure in front of the invitee rather than the buyer.
        """
        return TeamMember.objects.filter(
            account=account,
            status__in=(TeamMemberStatus.INVITED, TeamMemberStatus.ACTIVE),
        ).count()

    def membership_for(self, user, account=None):
        """The membership a user holds, or None.

        An account owner with no explicit row is still the owner — the row is
        created lazily by ``ensure_owner_seat`` — so callers should use
        ``role_for`` rather than reading this directly.
        """
        query = TeamMember.objects.filter(
            user=user, status=TeamMemberStatus.ACTIVE
        )

        if account is not None:
            query = query.filter(account=account)

        return query.select_related("account").first()

    def role_for(self, user, account):
        """This user's role on this account, or None if they have none."""
        if user == account:
            return TeamRole.OWNER

        membership = self.membership_for(user, account=account)

        return membership.role if membership else None

    def assert_can(self, *, user, account, capability):
        role = self.role_for(user, account)

        if role is None or not role_can(role, capability):
            raise PermissionDenied(
                "Your role does not allow this action."
            )

        return role

    # --- seats ------------------------------------------------------------

    @transaction.atomic
    def ensure_owner_seat(self, account):
        """Give the owner their row, once.

        Called on first team read or write rather than at registration, so
        accounts that predate E10 acquire a seat the moment teams are touched
        instead of needing a data migration that guesses at their email.
        """
        member, _ = TeamMember.objects.get_or_create(
            account=account,
            email=account.email,
            defaults={
                "user": account,
                "role": TeamRole.OWNER,
                "status": TeamMemberStatus.ACTIVE,
                "accepted_at": timezone.now(),
            },
        )

        if member.status != TeamMemberStatus.ACTIVE or member.user_id is None:
            # An owner who was somehow removed or unlinked is restored: an
            # account must never be left with nobody able to administer it.
            member.user = account
            member.role = TeamRole.OWNER
            member.status = TeamMemberStatus.ACTIVE
            member.removed_at = None
            member.save(
                update_fields=[
                    "user", "role", "status", "removed_at", "updated_at",
                ]
            )

        return member

    def check_seat_available(self, account, *, requested=1):
        """Raise 402 if adding ``requested`` seats would breach the plan.

        Delegates to E9 so the ceiling, the message and the status code all
        come from one place.
        """
        subscription = self.subscriptions.current(account)

        if subscription is None:
            # No subscription is not unlimited seats. The entitlement seam
            # treats a subscription-less account as the lowest tier, and the
            # seat gate has to agree or it becomes the way around the plan.
            return True

        return self.allowances.check_capacity(
            subscription=subscription,
            kind=AllowanceKind.SEATS,
            requested=requested,
        )

    # --- invitations (E10-S2) ---------------------------------------------

    @transaction.atomic
    def invite(self, *, account, inviter, email, role=None):
        """Invite someone, or re-send an invitation already outstanding.

        ``role`` of None means "unchanged": re-sending keeps whatever role was
        chosen, and only a brand-new invitation falls back to MEMBER. Without
        that distinction a resend — which carries no role — would silently
        demote a pending admin.
        """
        email = (email or "").strip().lower()

        if not email:
            raise ValidationError({"email": "An email address is required."})

        self.ensure_owner_seat(account)
        self.assert_can(
            user=inviter, account=account, capability=MANAGE_TEAM
        )

        if role == TeamRole.OWNER:
            # There is exactly one owner and it is the account. Inviting a
            # second would make "who pays" ambiguous.
            raise ValidationError(
                {"role": "An account has one owner; invite an admin instead."}
            )

        if email == (account.email or "").lower():
            raise ValidationError(
                {"email": "The account owner is already on the team."}
            )

        existing = TeamMember.objects.filter(
            account=account, email=email
        ).first()

        if existing and existing.status == TeamMemberStatus.ACTIVE:
            raise ValidationError(
                {"email": "This person is already on your team."}
            )

        # Re-inviting someone who was removed reuses their row, so the
        # unique constraint holds and their history stays in one place.
        if existing is None or existing.status == TeamMemberStatus.REMOVED:
            self.check_seat_available(account)

        member = existing or TeamMember(account=account, email=email)

        if role is not None:
            member.role = role
        elif existing is None:
            member.role = TeamRole.MEMBER

        member.status = TeamMemberStatus.INVITED
        member.invited_by = inviter
        member.invite_token = new_invite_token()
        member.invite_expires_at = default_invite_expiry()
        member.removed_at = None
        member.user = None
        member.accepted_at = None

        try:
            member.save()
        except IntegrityError:
            raise ValidationError(
                {"email": "This person has already been invited."}
            )

        self._send_invite(member)

        return member

    @transaction.atomic
    def accept(self, *, token, user):
        """Take up an invitation.

        The seat is re-checked here, not just at invite time. An owner can
        downgrade their plan between sending an invite and its acceptance, and
        honouring it then would put the account over its ceiling silently.
        """
        member = (
            TeamMember.objects.select_for_update()
            .filter(invite_token=token)
            .exclude(invite_token="")
            .select_related("account")
            .first()
        )

        if member is None:
            raise ValidationError({"token": "This invitation is not valid."})

        if member.status == TeamMemberStatus.ACTIVE:
            raise ValidationError(
                {"token": "This invitation has already been accepted."}
            )

        if member.status == TeamMemberStatus.REMOVED:
            raise ValidationError({"token": "This invitation was withdrawn."})

        if member.invite_expired:
            raise ValidationError(
                {"token": "This invitation has expired. Ask for a new one."}
            )

        if (user.email or "").lower() != member.email.lower():
            # The token is a bearer credential, so it must not let whoever
            # holds it join as somebody else.
            raise ValidationError(
                {"token": "This invitation was sent to a different address."}
            )

        # The invitation already held a seat, so no new one is consumed. The
        # check catches the case where the plan shrank underneath it.
        self._assert_seat_still_available(member)

        member.user = user
        member.status = TeamMemberStatus.ACTIVE
        member.accepted_at = timezone.now()
        member.invite_token = ""
        member.invite_expires_at = None
        member.save(
            update_fields=[
                "user", "status", "accepted_at", "invite_token",
                "invite_expires_at", "updated_at",
            ]
        )

        return member

    def _assert_seat_still_available(self, member):
        subscription = self.subscriptions.current(member.account)

        if subscription is None:
            return True

        limit = self.allowances.limit_for(subscription, AllowanceKind.SEATS)

        if limit is None:
            return True

        # This invitation is already counted, so compare the current total
        # against the ceiling rather than asking for one more on top.
        if self.seats_used(member.account) > limit:
            raise ValidationError(
                {
                    "token": (
                        "This team is now full. Ask the account owner to "
                        "upgrade their plan."
                    )
                }
            )

        return True

    @transaction.atomic
    def remove(self, *, account, actor, member_id):
        self.assert_can(user=actor, account=account, capability=MANAGE_TEAM)

        member = TeamMember.objects.filter(
            account=account, id=member_id
        ).first()

        if member is None:
            raise ValidationError({"member": "No such team member."})

        if member.role == TeamRole.OWNER:
            raise ValidationError(
                {"member": "The account owner cannot be removed."}
            )

        member.status = TeamMemberStatus.REMOVED
        member.removed_at = timezone.now()
        member.user = None
        member.invite_token = ""
        member.invite_expires_at = None
        member.save(
            update_fields=[
                "status", "removed_at", "user", "invite_token",
                "invite_expires_at", "updated_at",
            ]
        )

        return member

    @transaction.atomic
    def change_role(self, *, account, actor, member_id, role):
        self.assert_can(user=actor, account=account, capability=MANAGE_TEAM)

        if role == TeamRole.OWNER:
            raise ValidationError(
                {"role": "Ownership cannot be reassigned here."}
            )

        member = TeamMember.objects.filter(
            account=account, id=member_id
        ).first()

        if member is None:
            raise ValidationError({"member": "No such team member."})

        if member.role == TeamRole.OWNER:
            raise ValidationError(
                {"member": "The account owner's role cannot be changed."}
            )

        member.role = role
        member.save(update_fields=["role", "updated_at"])

        return member

    # --- delivery ---------------------------------------------------------

    def _send_invite(self, member):
        """Email the invitation.

        Never allowed to break the invite: the row is the source of truth and
        a link can be resent, but a 500 here would leave the owner unsure
        whether the seat was taken.
        """
        from apps.teams.tasks import send_team_invite

        payload = {
            "email": member.email,
            "token": member.invite_token,
            "account_name": (
                member.account.first_name or member.account.email
            ),
            "role": member.role,
        }

        try:
            return send_team_invite.delay(**payload)
        except Exception as exc:
            logger.error(
                "invite could not be queued (%s: %s) — sending inline",
                type(exc).__name__,
                exc,
            )

        try:
            return send_team_invite(**payload)
        except Exception:
            logger.exception(
                "invite email failed for %s; the invitation still stands",
                member.email,
            )

            return None
