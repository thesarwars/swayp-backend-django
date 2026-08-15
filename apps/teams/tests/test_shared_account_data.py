"""A team shares the account's data (E10-S1).

Seats, roles and gates were enforced before this, but every read still scoped
to the signed-in user — so an invited member saw an empty product and, worse,
``POST /billing/subscription/`` would have started them a *second* subscription
on their own user while the owner kept paying for the first.

The rule: account-owned data keys on the acting account. Personal things —
notifications, anything under authentication — stay on the signed-in user.

These tests go through the API, because the bug was never in the services. It
was in what the views handed them.
"""

import datetime as dt

from django.test import TestCase
from rest_framework.test import APIClient

from apps.banking.factories import BankAccountFactory, BankConnectionFactory
from apps.billing.factories import SubscriptionFactory
from apps.billing.models import Plan, PlanCode, Subscription
from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.teams.factories import ActiveMemberFactory
from apps.teams.models import TeamRole
from apps.vendors.factories import UserFactory, VendorPaymentMethodFactory

D = dt.date


def plan(code):
    return Plan.objects.get(code=code)


class SharedAccountDataTests(TestCase):

    def setUp(self):
        self.subscription = SubscriptionFactory(plan=plan(PlanCode.STANDARD))
        self.owner = self.subscription.account

        connection = BankConnectionFactory(
            user=self.owner, institution_name="Chase Bank"
        )
        BankAccountFactory(
            connection=connection, is_default_funding_source=True
        )

        self.bill = BillFactory(user=self.owner, anchor_date=D(2026, 9, 1))
        self.bill.vendor.name = "WeWork"
        self.bill.vendor.save()
        self.bill.payment_method = VendorPaymentMethodFactory(
            vendor=self.bill.vendor
        )
        self.bill.save(update_fields=["payment_method"])

        self.occurrence = BillOccurrenceFactory(
            bill=self.bill, due_date=D(2026, 9, 1), amount="3200.00"
        )

        self.member = ActiveMemberFactory(
            account=self.owner, role=TeamRole.MEMBER
        )
        self.admin = ActiveMemberFactory(
            account=self.owner, role=TeamRole.ADMIN
        )

        self.owner_client = APIClient()
        self.owner_client.force_authenticate(user=self.owner)

        self.member_client = APIClient()
        self.member_client.force_authenticate(user=self.member.user)

        self.stranger_client = APIClient()
        self.stranger_client.force_authenticate(user=UserFactory())

    # --- reads ------------------------------------------------------------

    def test_a_member_sees_the_accounts_bills(self):
        response = self.member_client.get("/api/v1/bills/occurrences")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]), 1)

    def test_a_member_sees_the_accounts_vendors(self):
        response = self.member_client.get("/api/v1/vendors")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["items"][0]["name"], "WeWork")

    def test_a_member_sees_the_accounts_banks(self):
        response = self.member_client.get("/api/v1/banking/accounts")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]), 1)

    def test_a_member_sees_the_accounts_dashboard(self):
        owner = self.owner_client.get("/api/v1/dashboard/home")
        member = self.member_client.get("/api/v1/dashboard/home")

        self.assertEqual(member.status_code, 200)
        self.assertEqual(
            member.data["data"]["stats"], owner.data["data"]["stats"]
        )

    def test_a_member_sees_the_accounts_bill_summary(self):
        owner = self.owner_client.get("/api/v1/bills/summary")
        member = self.member_client.get("/api/v1/bills/summary")

        self.assertEqual(member.data["data"], owner.data["data"])

    def test_a_stranger_sees_nothing(self):
        """Sharing is by membership, not by being signed in."""
        response = self.stranger_client.get("/api/v1/bills/occurrences")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], [])

    # --- writes -----------------------------------------------------------

    def test_a_bill_a_member_creates_belongs_to_the_account(self):
        """Otherwise it would vanish from the owner's view the moment the
        member closed the tab."""
        from apps.bill_categories.models import BillCategory
        from apps.bills.models.bill import Bill

        response = self.member_client.post(
            "/api/v1/bills/create",
            {
                "vendor": str(self.bill.vendor.id),
                "category": str(BillCategory.objects.first().id),
                "bill_type": "FIXED",
                "amount": "500.00",
                "frequency": "MONTHLY",
                "anchor_date": "2026-10-01",
                "autopay_mode": "REMIND",
            },
            format="json",
        )

        self.assertIn(response.status_code, (200, 201))

        created = Bill.objects.get(amount="500.00")
        self.assertEqual(created.user, self.owner)

    def test_the_owner_sees_what_a_member_created(self):
        from apps.bill_categories.models import BillCategory

        self.member_client.post(
            "/api/v1/bills/create",
            {
                "vendor": str(self.bill.vendor.id),
                "category": str(BillCategory.objects.first().id),
                "bill_type": "FIXED",
                "amount": "500.00",
                "frequency": "MONTHLY",
                "anchor_date": "2026-10-01",
                "autopay_mode": "REMIND",
            },
            format="json",
        )

        response = self.owner_client.get("/api/v1/bills")

        amounts = {str(row["amount"]) for row in response.data["data"]}
        self.assertIn("500.00", amounts)

    # --- billing ----------------------------------------------------------

    def test_a_member_sees_the_accounts_subscription(self):
        response = self.member_client.get("/api/v1/billing/subscription")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            str(response.data["data"]["id"]), str(self.subscription.id)
        )

    def test_a_member_cannot_start_a_second_subscription(self):
        """The bug this closes: it used to create one on their own user, so
        the account would have been paying twice over."""
        response = self.member_client.post(
            "/api/v1/billing/subscription",
            {"plan": "ENTERPRISE"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Subscription.objects.count(), 1)

    def test_an_admin_cannot_change_the_plan_either(self):
        """Only the owner: a plan change changes what the owner is charged."""
        client = APIClient()
        client.force_authenticate(user=self.admin.user)

        response = client.patch(
            "/api/v1/billing/subscription",
            {"plan": "ENTERPRISE"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_an_admin_can_still_read_billing(self):
        """Reads are exempt — everyone can see which plan they are on."""
        client = APIClient()
        client.force_authenticate(user=self.admin.user)

        self.assertEqual(
            client.get("/api/v1/billing/subscription").status_code, 200
        )
        self.assertEqual(
            client.get("/api/v1/billing/allowances").status_code, 200
        )

    def test_the_owner_can_still_change_the_plan(self):
        response = self.owner_client.patch(
            "/api/v1/billing/subscription",
            {"plan": "ENTERPRISE"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_a_member_sees_the_accounts_allowances(self):
        response = self.member_client.get("/api/v1/billing/allowances")

        self.assertEqual(response.status_code, 200)
        # Owner + member + admin.
        self.assertEqual(response.data["data"]["SEATS"]["used"], 3)

    # --- money ------------------------------------------------------------

    def test_an_admin_can_pay_the_accounts_bill(self):
        """The point of the whole feature: a colleague can do the work."""
        client = APIClient()
        client.force_authenticate(user=self.admin.user)

        created = client.post(
            "/api/v1/payments",
            {
                "occurrence_ids": [str(self.occurrence.id)],
                "rail": "ACH_STANDARD",
            },
            format="json",
        )

        self.assertEqual(created.status_code, 201)

        payment_id = created.data["data"]["payments"][0]["id"]
        confirmed = client.post(
            f"/api/v1/payments/{payment_id}/confirm",
            {
                "authorization_text": created.data["data"][
                    "authorization_text"
                ]
            },
            format="json",
        )

        self.assertEqual(confirmed.status_code, 200)

    def test_the_owner_sees_a_payment_an_admin_made(self):
        client = APIClient()
        client.force_authenticate(user=self.admin.user)

        client.post(
            "/api/v1/payments",
            {
                "occurrence_ids": [str(self.occurrence.id)],
                "rail": "ACH_STANDARD",
            },
            format="json",
        )

        response = self.owner_client.get("/api/v1/payments/history")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.data["pagination"]["totalItems"], 1)

    def test_a_member_can_prepare_but_not_authorize(self):
        created = self.member_client.post(
            "/api/v1/payments",
            {
                "occurrence_ids": [str(self.occurrence.id)],
                "rail": "ACH_STANDARD",
            },
            format="json",
        )

        self.assertEqual(created.status_code, 201)

        payment_id = created.data["data"]["payments"][0]["id"]
        confirmed = self.member_client.post(
            f"/api/v1/payments/{payment_id}/confirm",
            {"authorization_text": "I authorize this payment."},
            format="json",
        )

        self.assertEqual(confirmed.status_code, 403)


class SoloAccountUnaffectedTests(TestCase):
    """Everyone is solo until they invite someone.

    The regression that would hurt most: quietly changing behaviour for the
    accounts that have no team at all, which today is all of them.
    """

    def setUp(self):
        self.user = UserFactory()
        SubscriptionFactory(plan=plan(PlanCode.FOUNDING), account=self.user)

        self.bill = BillFactory(user=self.user, anchor_date=D(2026, 9, 1))
        BillOccurrenceFactory(
            bill=self.bill, due_date=D(2026, 9, 1), amount="100.00"
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_a_solo_user_sees_their_own_data(self):
        response = self.client.get("/api/v1/bills/occurrences")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["data"]), 1)

    def test_a_solo_user_is_the_owner_and_holds_every_capability(self):
        response = self.client.get("/api/v1/teams/me")

        self.assertTrue(response.data["data"]["is_owner"])
        self.assertIn("send_money", response.data["data"]["capabilities"])

    def test_a_solo_user_can_still_change_their_plan(self):
        response = self.client.patch(
            "/api/v1/billing/subscription",
            {"plan": "STANDARD"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_a_solo_user_can_still_connect_a_bank(self):
        response = self.client.post(
            "/api/v1/banking/link/exchange",
            {"public_token": "public-mock-chase", "consent_accepted": True},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
