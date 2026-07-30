"""Team membership and roles (E10-S1).

A row here is a *seat*, and the seat is what the plan sells. That is why the
owner has a row too: "Founding — 3 seats" has to mean three people who can log
in, or the pricing page and the headcount disagree the moment anyone reads
either one.
"""

import datetime as dt
import secrets

from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel

#: How long an invitation stays acceptable. Long enough to survive a weekend
#: and an inbox backlog, short enough that a leaked link goes stale.
INVITE_TTL_DAYS = 14


class TeamRole(models.TextChoices):
    OWNER = "OWNER", "Owner"
    ADMIN = "ADMIN", "Admin"
    MEMBER = "MEMBER", "Member"


class TeamMemberStatus(models.TextChoices):
    INVITED = "INVITED", "Invited"
    ACTIVE = "ACTIVE", "Active"
    REMOVED = "REMOVED", "Removed"


#: Statuses that occupy a seat. An invitation holds one deliberately — if it
#: did not, an owner on a 3-seat plan could send thirty invites and only
#: discover the problem when the thirty-first person tried to accept, which
#: puts the failure in front of the wrong person.
OCCUPYING_STATUSES = (TeamMemberStatus.INVITED, TeamMemberStatus.ACTIVE)


def new_invite_token():
    # 32 bytes url-safe. The token is the only thing standing between an email
    # and access to an account's bills, so it is generated the same way a
    # session token would be, never from a uuid or a counter.
    return secrets.token_urlsafe(32)


def default_invite_expiry():
    return timezone.now() + dt.timedelta(days=INVITE_TTL_DAYS)


class TeamMember(BaseModel):
    """One person's seat on an account.

    ``account`` is the owner whose plan pays. ``user`` is null until the
    invitation is accepted, because an invite is sent to an email address that
    may not have a Swayp login yet — and must not require one, or inviting a
    colleague would mean asking them to register first.
    """

    account = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="team_members",
    )

    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="memberships",
        null=True,
        blank=True,
    )

    email = models.EmailField()

    role = models.CharField(
        max_length=10,
        choices=TeamRole.choices,
        default=TeamRole.MEMBER,
    )

    status = models.CharField(
        max_length=10,
        choices=TeamMemberStatus.choices,
        default=TeamMemberStatus.INVITED,
    )

    # --- invitation -------------------------------------------------------

    invite_token = models.CharField(max_length=64, blank=True, db_index=True)
    invite_expires_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        related_name="sent_invites",
        null=True,
        blank=True,
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "team_members"
        ordering = ["created_at"]
        constraints = [
            # One row per address per account. A removed member keeps their
            # row, so re-inviting them revives it rather than creating a
            # second history for the same person.
            models.UniqueConstraint(
                fields=["account", "email"],
                name="uniq_member_per_account",
            ),
        ]
        indexes = [
            models.Index(fields=["account", "status"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        return f"{self.email} ({self.role}/{self.status})"

    @property
    def occupies_seat(self):
        return self.status in OCCUPYING_STATUSES

    @property
    def invite_expired(self):
        if self.invite_expires_at is None:
            return False

        return timezone.now() > self.invite_expires_at

    @property
    def can_accept(self):
        return (
            self.status == TeamMemberStatus.INVITED
            and not self.invite_expired
        )
