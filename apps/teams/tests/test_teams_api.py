"""The teams API and the role gates it enforces (E10-S1 … E10-S3).

The permission matrix is only real if the API applies it. These tests go
through the endpoints rather than the service, because a matrix that is
correct in ``permissions.py`` and unenforced at the view is decoration.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.banking.factories import BankAccountFactory, BankConnectionFactory
from apps.billing.factories import SubscriptionFactory
from apps.billing.models import Plan, PlanCode
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.common.enums import PaymentRail
from apps.teams.factories import ActiveMemberFactory
from apps.teams.models import TeamMember, TeamMemberStatus, TeamRole
from apps.vendors.factories import UserFactory, VendorPaymentMethodFactory

import datetime as dt

D = dt.date


def plan(code):
    return Plan.objects.get(code=code)


class TeamAPITests(TestCase):

    def setUp(self):
        self.subscription = SubscriptionFactory(plan=plan(PlanCode.STANDARD))
        self.owner = self.subscription.account

        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def test_the_member_list_includes_the_owner(self):
        response = self.client.get("/api/v1/teams/members")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]), 1)
        self.assertEqual(response.data["data"][0]["role"], TeamRole.OWNER)

    def test_the_invite_token_is_never_returned(self):
        """It is a bearer credential and belongs only in the invitee's
        inbox — not in a list every teammate can read."""
        self.client.post(
            "/api/v1/teams/invite",
            {"email": "new@example.com"},
            format="json",
        )

        response = self.client.get("/api/v1/teams/members")
        body = str(response.data)

        self.assertNotIn("invite_token", body)

        member = TeamMember.objects.get(email="new@example.com")
        self.assertNotIn(member.invite_token, body)

    def test_inviting_returns_201(self):
        response = self.client.post(
            "/api/v1/teams/invite",
            {"email": "new@example.com", "role": "ADMIN"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["data"]["status"], "INVITED")
        self.assertEqual(response.data["data"]["role"], "ADMIN")

    def test_my_role_reports_capabilities(self):
        response = self.client.get("/api/v1/teams/me")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["is_owner"])
        self.assertIn("send_money", response.data["data"]["capabilities"])

    def test_a_member_sees_a_reduced_capability_list(self):
        member = ActiveMemberFactory(
            account=self.owner, role=TeamRole.MEMBER
        )

        client = APIClient()
        client.force_authenticate(user=member.user)

        response = client.get("/api/v1/teams/me")

        self.assertEqual(response.data["data"]["role"], "MEMBER")
        self.assertFalse(response.data["data"]["is_owner"])
        self.assertNotIn(
            "send_money", response.data["data"]["capabilities"]
        )

    def test_a_member_acts_on_the_inviting_account(self):
        """Not on a private empty account of their own."""
        member = ActiveMemberFactory(account=self.owner)

        client = APIClient()
        client.force_authenticate(user=member.user)

        response = client.get("/api/v1/teams/me")

        self.assertEqual(
            str(response.data["data"]["account_id"]), str(self.owner.id)
        )

    def test_accepting_through_the_api(self):
        self.client.post(
            "/api/v1/teams/invite",
            {"email": "joiner@example.com"},
            format="json",
        )
        member = TeamMember.objects.get(email="joiner@example.com")

        joiner = UserFactory(email="joiner@example.com")
        client = APIClient()
        client.force_authenticate(user=joiner)

        response = client.post(
            "/api/v1/teams/invite/accept",
            {"token": member.invite_token},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["status"], "ACTIVE")

    def test_removing_a_member(self):
        member = ActiveMemberFactory(account=self.owner)

        response = self.client.delete(
            f"/api/v1/teams/members/{member.id}"
        )

        self.assertEqual(response.status_code, 200)

        member.refresh_from_db()
        self.assertEqual(member.status, TeamMemberStatus.REMOVED)

    def test_changing_a_role(self):
        member = ActiveMemberFactory(account=self.owner)

        response = self.client.patch(
            f"/api/v1/teams/members/{member.id}",
            {"role": "ADMIN"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["role"], "ADMIN")

    def test_a_member_cannot_invite_through_the_api(self):
        member = ActiveMemberFactory(
            account=self.owner, role=TeamRole.MEMBER
        )

        client = APIClient()
        client.force_authenticate(user=member.user)

        response = client.post(
            "/api/v1/teams/invite",
            {"email": "nope@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_the_seat_limit_answers_402_not_403(self):
        """Authorised, just needs a bigger plan — so the client can upsell."""
        account = SubscriptionFactory(plan=plan(PlanCode.FOUNDING)).account

        client = APIClient()
        client.force_authenticate(user=account)
        client.get("/api/v1/teams/members")

        for index in range(2):
            client.post(
                "/api/v1/teams/invite",
                {"email": f"seat{index}@example.com"},
                format="json",
            )

        response = client.post(
            "/api/v1/teams/invite",
            {"email": "overflow@example.com"},
            format="json",
        )

        self.assertEqual(response.status_code, 402)

    def test_the_allowance_endpoint_reflects_the_team(self):
        self.client.get("/api/v1/teams/members")
        self.client.post(
            "/api/v1/teams/invite",
            {"email": "counted@example.com"},
            format="json",
        )

        response = self.client.get("/api/v1/billing/allowances")

        self.assertEqual(response.data["data"]["SEATS"]["used"], 2)


class MoneyGateTests(TestCase):
    """The matrix has to hold where it matters: money leaving the account."""

    def setUp(self):
        self.subscription = SubscriptionFactory(plan=plan(PlanCode.STANDARD))
        self.owner = self.subscription.account

        connection = BankConnectionFactory(user=self.owner)
        BankAccountFactory(
            connection=connection, is_default_funding_source=True
        )

        self.bill = BillFactory(user=self.owner, anchor_date=D(2026, 9, 1))
        self.bill.payment_method = VendorPaymentMethodFactory(
            vendor=self.bill.vendor
        )
        self.bill.save(update_fields=["payment_method"])

        self.member = ActiveMemberFactory(
            account=self.owner, role=TeamRole.MEMBER
        )

        self.member_client = APIClient()
        self.member_client.force_authenticate(user=self.member.user)

    def a_payment(self):
        occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=D(2026, 9, 1), amount="900.00"
        )

        client = APIClient()
        client.force_authenticate(user=self.owner)

        response = client.post(
            "/api/v1/payments",
            {
                "occurrence_ids": [str(occurrence.id)],
                "rail": PaymentRail.ACH_STANDARD,
            },
            format="json",
        )

        return response.data["data"]["payments"][0]["id"]

    def test_a_member_cannot_confirm_a_payment(self):
        payment_id = self.a_payment()

        response = self.member_client.post(
            f"/api/v1/payments/{payment_id}/confirm",
            {"authorization_text": "I authorize this payment."},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_a_member_cannot_connect_a_bank(self):
        response = self.member_client.post(
            "/api/v1/banking/link/exchange",
            {"public_token": "public-mock-chase", "consent_accepted": True},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_an_admin_can_confirm_a_payment(self):
        admin = ActiveMemberFactory(
            account=self.owner, role=TeamRole.ADMIN
        )
        payment_id = self.a_payment()

        client = APIClient()
        client.force_authenticate(user=admin.user)

        response = client.post(
            f"/api/v1/payments/{payment_id}/confirm",
            {"authorization_text": "I authorize this payment."},
            format="json",
        )

        self.assertNotEqual(response.status_code, 403)

    def test_a_solo_user_is_unaffected(self):
        """Everyone is solo until they invite someone; the gate must not
        change behaviour for an account with no team."""
        payment_id = self.a_payment()

        client = APIClient()
        client.force_authenticate(user=self.owner)

        response = client.post(
            f"/api/v1/payments/{payment_id}/confirm",
            {"authorization_text": "I authorize this payment."},
            format="json",
        )

        self.assertNotEqual(response.status_code, 403)


class EntityAPITests(TestCase):

    def setUp(self):
        self.subscription = SubscriptionFactory(
            plan=plan(PlanCode.ENTERPRISE)
        )
        self.owner = self.subscription.account

        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def test_creating_an_entity(self):
        response = self.client.post(
            "/api/v1/teams/entities",
            {"legal_name": "Acme Holdings LLC", "ein": "12-3456789"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.data["data"]["legal_name"], "Acme Holdings LLC"
        )

    def test_listing_excludes_archived(self):
        created = self.client.post(
            "/api/v1/teams/entities",
            {"legal_name": "Gone LLC"},
            format="json",
        )
        entity_id = created.data["data"]["id"]

        self.client.delete(f"/api/v1/teams/entities/{entity_id}")

        response = self.client.get("/api/v1/teams/entities")

        self.assertEqual(response.data["data"], [])

    def test_a_non_enterprise_account_cannot_add_a_second(self):
        account = SubscriptionFactory(plan=plan(PlanCode.FOUNDING)).account

        client = APIClient()
        client.force_authenticate(user=account)

        client.post(
            "/api/v1/teams/entities",
            {"legal_name": "First LLC"},
            format="json",
        )
        response = client.post(
            "/api/v1/teams/entities",
            {"legal_name": "Second LLC"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("plan", response.data["errors"])

    def test_a_member_cannot_manage_entities(self):
        member = ActiveMemberFactory(
            account=self.owner, role=TeamRole.MEMBER
        )

        client = APIClient()
        client.force_authenticate(user=member.user)

        response = client.post(
            "/api/v1/teams/entities",
            {"legal_name": "Sneaky LLC"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_another_accounts_entity_is_404(self):
        from apps.teams.factories import EntityFactory

        theirs = EntityFactory()

        response = self.client.patch(
            f"/api/v1/teams/entities/{theirs.id}",
            {"legal_name": "Mine Now LLC"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
