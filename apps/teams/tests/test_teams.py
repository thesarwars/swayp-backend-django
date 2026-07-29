"""Seats, invitations, roles and entities (E10-S1 … E10-S3)."""

import datetime as dt

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.billing.factories import SubscriptionFactory
from apps.billing.models import AllowanceKind, Plan, PlanCode
from apps.billing.services.allowance_service import AllowanceService
from apps.billing.services.subscription_service import SubscriptionService
from apps.common.exceptions import PlanLimitExceededException
from apps.teams.factories import ActiveMemberFactory, EntityFactory
from apps.teams.models import (
    Entity,
    EntityStatus,
    TeamMember,
    TeamMemberStatus,
    TeamRole,
)
from apps.teams.permissions import (
    MANAGE_BILLING,
    MANAGE_BILLS,
    SEND_MONEY,
    capabilities_for,
    role_can,
)
from apps.teams.services.entity_service import EntityService
from apps.teams.services.team_service import TeamService
from apps.vendors.factories import UserFactory


def plan(code):
    return Plan.objects.get(code=code)


class SeatCountingTests(TestCase):
    """E10-S1: the owner occupies a seat, and an invite holds one."""

    def setUp(self):
        self.service = TeamService()
        self.subscription = SubscriptionFactory(plan=plan(PlanCode.FOUNDING))
        self.account = self.subscription.account

    def test_the_owner_occupies_a_seat(self):
        """'Founding — 3 seats' has to mean three people who can sign in."""
        self.service.ensure_owner_seat(self.account)

        self.assertEqual(self.service.seats_used(self.account), 1)

    def test_the_owner_seat_is_created_only_once(self):
        for _ in range(3):
            self.service.ensure_owner_seat(self.account)

        self.assertEqual(
            TeamMember.objects.filter(
                account=self.account, role=TeamRole.OWNER
            ).count(),
            1,
        )

    def test_a_pending_invitation_holds_a_seat(self):
        """Otherwise thirty invites on a three-seat plan all look fine until
        the thirty-first person tries to accept."""
        self.service.ensure_owner_seat(self.account)
        self.service.invite(
            account=self.account,
            inviter=self.account,
            email="pending@example.com",
        )

        self.assertEqual(self.service.seats_used(self.account), 2)

    def test_a_removed_member_frees_their_seat(self):
        self.service.ensure_owner_seat(self.account)
        member = self.service.invite(
            account=self.account,
            inviter=self.account,
            email="leaver@example.com",
        )

        self.assertEqual(self.service.seats_used(self.account), 2)

        self.service.remove(
            account=self.account, actor=self.account, member_id=member.id
        )

        self.assertEqual(self.service.seats_used(self.account), 1)

    def test_the_billing_screen_and_the_gate_agree(self):
        """Seats derive from these rows, so the number shown is the number
        enforced — the same rule banks already follow."""
        self.service.ensure_owner_seat(self.account)
        self.service.invite(
            account=self.account,
            inviter=self.account,
            email="one@example.com",
        )

        summary = AllowanceService().summary(self.subscription)

        self.assertEqual(summary["SEATS"]["used"], 2)
        self.assertEqual(summary["SEATS"]["remaining"], 1)

    def test_seats_are_not_reset_by_a_new_cycle(self):
        self.service.ensure_owner_seat(self.account)

        SubscriptionService().renew(self.subscription)
        AllowanceService().reset_metered(self.subscription)

        self.assertEqual(
            AllowanceService().used(self.subscription, AllowanceKind.SEATS), 1
        )


class SeatLimitTests(TestCase):
    """E10-S1 AC: blocked at the plan limit, unlimited on Enterprise."""

    def setUp(self):
        self.service = TeamService()

    def account_on(self, code):
        subscription = SubscriptionFactory(plan=plan(code))
        self.service.ensure_owner_seat(subscription.account)

        return subscription.account

    def fill(self, account, count):
        for index in range(count):
            self.service.invite(
                account=account,
                inviter=account,
                email=f"seat{index}@example.com",
            )

    def test_founding_stops_at_three_including_the_owner(self):
        account = self.account_on(PlanCode.FOUNDING)

        self.fill(account, 2)  # owner + 2 = 3

        with self.assertRaises(PlanLimitExceededException):
            self.service.invite(
                account=account, inviter=account, email="fourth@example.com"
            )

    def test_the_seat_limit_error_is_402(self):
        account = self.account_on(PlanCode.FOUNDING)
        self.fill(account, 2)

        with self.assertRaises(PlanLimitExceededException) as ctx:
            self.service.invite(
                account=account, inviter=account, email="fourth@example.com"
            )

        self.assertEqual(ctx.exception.status_code, 402)
        self.assertIn("seat", str(ctx.exception.detail).lower())

    def test_standard_allows_ten_including_the_owner(self):
        account = self.account_on(PlanCode.STANDARD)

        self.fill(account, 9)

        self.assertEqual(self.service.seats_used(account), 10)

        with self.assertRaises(PlanLimitExceededException):
            self.service.invite(
                account=account, inviter=account, email="eleventh@example.com"
            )

    def test_enterprise_is_unlimited(self):
        account = self.account_on(PlanCode.ENTERPRISE)

        self.fill(account, 25)

        self.assertEqual(self.service.seats_used(account), 26)

    def test_removing_someone_makes_room_again(self):
        account = self.account_on(PlanCode.FOUNDING)
        self.fill(account, 2)

        member = TeamMember.objects.filter(
            account=account, role=TeamRole.MEMBER
        ).first()
        self.service.remove(
            account=account, actor=account, member_id=member.id
        )

        # No raise.
        self.service.invite(
            account=account, inviter=account, email="replacement@example.com"
        )

        self.assertEqual(self.service.seats_used(account), 3)


class InvitationTests(TestCase):
    """E10-S2."""

    def setUp(self):
        self.service = TeamService()
        self.subscription = SubscriptionFactory(plan=plan(PlanCode.STANDARD))
        self.account = self.subscription.account
        self.service.ensure_owner_seat(self.account)

    def invite(self, email="invitee@example.com", role=TeamRole.MEMBER):
        return self.service.invite(
            account=self.account,
            inviter=self.account,
            email=email,
            role=role,
        )

    def test_an_invitation_carries_a_token_and_an_expiry(self):
        member = self.invite()

        self.assertTrue(member.invite_token)
        self.assertIsNotNone(member.invite_expires_at)
        self.assertEqual(member.status, TeamMemberStatus.INVITED)

    def test_the_email_is_normalised(self):
        member = self.invite(email="  Mixed.Case@Example.COM  ")

        self.assertEqual(member.email, "mixed.case@example.com")

    def test_accepting_links_the_user_and_activates_the_seat(self):
        member = self.invite()
        user = UserFactory(email=member.email)

        accepted = self.service.accept(token=member.invite_token, user=user)

        self.assertEqual(accepted.status, TeamMemberStatus.ACTIVE)
        self.assertEqual(accepted.user, user)
        self.assertIsNotNone(accepted.accepted_at)

    def test_the_token_is_consumed_on_acceptance(self):
        """Single use — a link that keeps working is a standing credential."""
        member = self.invite()
        user = UserFactory(email=member.email)

        self.service.accept(token=member.invite_token, user=user)
        member.refresh_from_db()

        self.assertEqual(member.invite_token, "")

    def test_accepting_twice_is_refused(self):
        from rest_framework.exceptions import ValidationError

        member = self.invite()
        user = UserFactory(email=member.email)
        token = member.invite_token

        self.service.accept(token=token, user=user)

        with self.assertRaises(ValidationError):
            self.service.accept(token=token, user=user)

    def test_an_expired_invitation_is_refused(self):
        from rest_framework.exceptions import ValidationError

        member = self.invite()
        member.invite_expires_at = timezone.now() - dt.timedelta(minutes=1)
        member.save(update_fields=["invite_expires_at"])

        user = UserFactory(email=member.email)

        with self.assertRaises(ValidationError):
            self.service.accept(token=member.invite_token, user=user)

    def test_a_token_cannot_be_used_by_a_different_address(self):
        """The token is a bearer credential; it must not let whoever holds it
        join as somebody else."""
        from rest_framework.exceptions import ValidationError

        member = self.invite()
        stranger = UserFactory(email="stranger@example.com")

        with self.assertRaises(ValidationError):
            self.service.accept(token=member.invite_token, user=stranger)

    def test_an_unknown_token_is_refused(self):
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.service.accept(
                token="not-a-real-token", user=UserFactory()
            )

    def test_inviting_the_same_address_twice_is_refused_once_active(self):
        from rest_framework.exceptions import ValidationError

        member = self.invite()
        user = UserFactory(email=member.email)
        self.service.accept(token=member.invite_token, user=user)

        with self.assertRaises(ValidationError):
            self.invite(email=member.email)

    def test_re_inviting_a_pending_address_reissues_the_token(self):
        """Not a duplicate row — the unique constraint would reject it, and
        the owner just wants the email resent."""
        first = self.invite()
        original = first.invite_token

        second = self.invite()

        self.assertEqual(first.id, second.id)
        self.assertNotEqual(second.invite_token, original)
        self.assertEqual(
            TeamMember.objects.filter(email=first.email).count(), 1
        )

    def test_resending_does_not_silently_demote_an_admin(self):
        """A resend carries no role. Defaulting it to MEMBER would quietly
        strip an outstanding admin invitation of its role."""
        admin = self.service.invite(
            account=self.account,
            inviter=self.account,
            email="admin@example.com",
            role=TeamRole.ADMIN,
        )

        resent = self.service.invite(
            account=self.account,
            inviter=self.account,
            email="admin@example.com",
        )

        self.assertEqual(resent.id, admin.id)
        self.assertEqual(resent.role, TeamRole.ADMIN)

    def test_a_resend_can_still_change_the_role_on_purpose(self):
        self.service.invite(
            account=self.account,
            inviter=self.account,
            email="admin@example.com",
            role=TeamRole.ADMIN,
        )

        changed = self.service.invite(
            account=self.account,
            inviter=self.account,
            email="admin@example.com",
            role=TeamRole.MEMBER,
        )

        self.assertEqual(changed.role, TeamRole.MEMBER)

    def test_a_brand_new_invitation_defaults_to_member(self):
        self.assertEqual(self.invite().role, TeamRole.MEMBER)

    def test_re_inviting_a_removed_person_revives_their_row(self):
        member = self.invite()
        self.service.remove(
            account=self.account, actor=self.account, member_id=member.id
        )

        revived = self.invite(email=member.email)

        self.assertEqual(revived.id, member.id)
        self.assertEqual(revived.status, TeamMemberStatus.INVITED)

    def test_the_owner_cannot_be_invited(self):
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.invite(email=self.account.email)

    def test_a_second_owner_cannot_be_invited(self):
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.invite(email="co-owner@example.com", role=TeamRole.OWNER)

    def test_acceptance_is_refused_if_the_plan_shrank_meanwhile(self):
        """E10-S2 AC edge: the owner downgraded after sending the invite."""
        from rest_framework.exceptions import ValidationError

        # Standard (10 seats): owner + 3 invited = 4.
        members = [
            self.invite(email=f"person{index}@example.com")
            for index in range(3)
        ]

        # Downgrade to Founding (3 seats). The account is now over.
        SubscriptionService().change_plan(
            account=self.account, plan_code=PlanCode.FOUNDING
        )

        user = UserFactory(email=members[-1].email)

        with self.assertRaises(ValidationError):
            self.service.accept(
                token=members[-1].invite_token, user=user
            )


class RoleTests(TestCase):

    def setUp(self):
        self.service = TeamService()
        self.subscription = SubscriptionFactory(plan=plan(PlanCode.STANDARD))
        self.account = self.subscription.account
        self.service.ensure_owner_seat(self.account)

    def test_the_owner_is_the_owner_without_a_lookup(self):
        self.assertEqual(
            self.service.role_for(self.account, self.account), TeamRole.OWNER
        )

    def test_a_member_holds_their_assigned_role(self):
        member = ActiveMemberFactory(
            account=self.account, role=TeamRole.ADMIN
        )

        self.assertEqual(
            self.service.role_for(member.user, self.account), TeamRole.ADMIN
        )

    def test_a_stranger_has_no_role(self):
        self.assertIsNone(
            self.service.role_for(UserFactory(), self.account)
        )

    def test_a_member_cannot_send_money(self):
        self.assertFalse(role_can(TeamRole.MEMBER, SEND_MONEY))

    def test_a_member_can_manage_bills(self):
        self.assertTrue(role_can(TeamRole.MEMBER, MANAGE_BILLS))

    def test_only_the_owner_manages_billing(self):
        self.assertTrue(role_can(TeamRole.OWNER, MANAGE_BILLING))
        self.assertFalse(role_can(TeamRole.ADMIN, MANAGE_BILLING))
        self.assertFalse(role_can(TeamRole.MEMBER, MANAGE_BILLING))

    def test_an_unknown_capability_is_denied(self):
        self.assertFalse(role_can(TeamRole.OWNER, "delete_the_internet"))

    def test_an_unknown_role_is_denied(self):
        self.assertFalse(role_can("SUPERUSER", MANAGE_BILLS))

    def test_capabilities_are_reported_for_the_client(self):
        self.assertIn(SEND_MONEY, capabilities_for(TeamRole.ADMIN))
        self.assertNotIn(SEND_MONEY, capabilities_for(TeamRole.MEMBER))

    def test_a_member_cannot_invite(self):
        from rest_framework.exceptions import PermissionDenied

        member = ActiveMemberFactory(
            account=self.account, role=TeamRole.MEMBER
        )

        with self.assertRaises(PermissionDenied):
            self.service.invite(
                account=self.account,
                inviter=member.user,
                email="nope@example.com",
            )

    def test_an_admin_can_invite(self):
        admin = ActiveMemberFactory(
            account=self.account, role=TeamRole.ADMIN
        )

        invited = self.service.invite(
            account=self.account,
            inviter=admin.user,
            email="welcome@example.com",
        )

        self.assertEqual(invited.status, TeamMemberStatus.INVITED)

    def test_the_owner_cannot_be_removed(self):
        from rest_framework.exceptions import ValidationError

        owner_row = TeamMember.objects.get(
            account=self.account, role=TeamRole.OWNER
        )

        with self.assertRaises(ValidationError):
            self.service.remove(
                account=self.account,
                actor=self.account,
                member_id=owner_row.id,
            )

    def test_the_owner_role_cannot_be_reassigned(self):
        from rest_framework.exceptions import ValidationError

        member = ActiveMemberFactory(account=self.account)

        with self.assertRaises(ValidationError):
            self.service.change_role(
                account=self.account,
                actor=self.account,
                member_id=member.id,
                role=TeamRole.OWNER,
            )


class EntityTests(TestCase):
    """E10-S3."""

    def setUp(self):
        self.service = EntityService()

    def account_on(self, code):
        return SubscriptionFactory(plan=plan(code)).account

    def test_the_first_entity_is_allowed_on_any_plan(self):
        account = self.account_on(PlanCode.FOUNDING)

        entity = self.service.create(
            account=account, legal_name="Solo Trading LLC"
        )

        self.assertEqual(entity.status, EntityStatus.ACTIVE)

    def test_a_second_entity_requires_enterprise(self):
        from rest_framework.exceptions import ValidationError

        account = self.account_on(PlanCode.STANDARD)
        self.service.create(account=account, legal_name="First LLC")

        with self.assertRaises(ValidationError):
            self.service.create(account=account, legal_name="Second LLC")

    def test_enterprise_can_hold_many(self):
        account = self.account_on(PlanCode.ENTERPRISE)

        for index in range(5):
            self.service.create(
                account=account, legal_name=f"Entity {index} LLC"
            )

        self.assertEqual(self.service.count(account), 5)

    def test_duplicate_names_are_refused(self):
        from rest_framework.exceptions import ValidationError

        account = self.account_on(PlanCode.ENTERPRISE)
        self.service.create(account=account, legal_name="Acme LLC")

        with self.assertRaises(ValidationError):
            self.service.create(account=account, legal_name="Acme LLC")

    def test_archiving_hides_it_without_deleting_it(self):
        """Payments reference entities; deleting would orphan history."""
        account = self.account_on(PlanCode.ENTERPRISE)
        entity = self.service.create(account=account, legal_name="Old LLC")

        self.service.archive(account=account, entity_id=entity.id)

        self.assertEqual(self.service.count(account), 0)
        self.assertTrue(Entity.objects.filter(id=entity.id).exists())

    def test_another_accounts_entity_is_not_found(self):
        from rest_framework.exceptions import NotFound

        mine = self.account_on(PlanCode.ENTERPRISE)
        theirs = EntityFactory()

        with self.assertRaises(NotFound):
            self.service.get(mine, theirs.id)

    # --- billing feed (E9-S5) --------------------------------------------

    def test_the_first_three_entities_add_no_charge(self):
        account = self.account_on(PlanCode.ENTERPRISE)
        subscription = SubscriptionService().current(account)

        for index in range(3):
            self.service.create(
                account=account, legal_name=f"Included {index} LLC"
            )

        self.assertFalse(subscription.addons.exists())

    def test_the_fourth_entity_bills_seventy_nine(self):
        account = self.account_on(PlanCode.ENTERPRISE)
        subscription = SubscriptionService().current(account)

        for index in range(4):
            self.service.create(
                account=account, legal_name=f"Entity {index} LLC"
            )

        addon = subscription.addons.get(kind="EXTRA_ENTITY")

        self.assertEqual(addon.quantity, 1)
        self.assertEqual(str(addon.unit_price), "79.00")

    def test_archiving_an_entity_reduces_the_charge(self):
        """The add-on tracks the real structure, so nobody has to remember
        to tell billing."""
        account = self.account_on(PlanCode.ENTERPRISE)
        subscription = SubscriptionService().current(account)

        entities = [
            self.service.create(
                account=account, legal_name=f"Entity {index} LLC"
            )
            for index in range(5)
        ]

        self.assertEqual(
            subscription.addons.get(kind="EXTRA_ENTITY").quantity, 2
        )

        self.service.archive(account=account, entity_id=entities[-1].id)

        self.assertEqual(
            subscription.addons.get(kind="EXTRA_ENTITY").quantity, 1
        )


class EntityScopingTests(TestCase):
    """E10-S3 AC: the filter applies only once entities exist."""

    def setUp(self):
        from apps.teams.selectors.scoping import (
            default_entity,
            has_entities,
            scope_to_entity,
        )

        self.default_entity = default_entity
        self.has_entities = has_entities
        self.scope_to_entity = scope_to_entity
        self.account = UserFactory()

    def test_a_single_entity_account_is_untouched(self):
        """Everything stays null and every pre-E10 query keeps working."""
        self.assertFalse(self.has_entities(self.account))
        self.assertIsNone(self.default_entity(self.account))

    def test_one_entity_becomes_the_default(self):
        entity = EntityFactory(account=self.account)

        self.assertEqual(self.default_entity(self.account), entity)

    def test_several_entities_have_no_default(self):
        """Guessing would file a bill against the wrong company."""
        EntityFactory(account=self.account)
        EntityFactory(account=self.account)

        self.assertIsNone(self.default_entity(self.account))

    def test_an_archived_entity_is_not_counted(self):
        EntityFactory(account=self.account, status=EntityStatus.ARCHIVED)

        self.assertFalse(self.has_entities(self.account))

    def test_no_entity_id_returns_everything(self):
        entity = EntityFactory(account=self.account)
        queryset = Entity.objects.filter(account=self.account)

        self.assertEqual(
            list(self.scope_to_entity(queryset, self.account)), [entity]
        )
