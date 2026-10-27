"""Every role against every protected action (Teams roles).

Owner, Admin, Approver, Accountant (stored MEMBER) and Viewer. The role check
runs before the view does any work, so an action is called with ids that do
not exist: a refused role gets 403 ``role_forbidden``, an allowed one gets
past the gate to whatever the view answers next (400, 404, ...). That keeps
the matrix about permissions and nothing else.

The guard at the bottom fails when a new account-scoped write endpoint ships
without naming a capability, so a Viewer cannot write through it by default.
"""

import uuid

from django.test import TestCase
from django.urls import get_resolver
from rest_framework.test import APIClient

from apps.bills.models.standing_authorization import StandingAuthorization
from apps.bills.tests.test_autopay_consent import AutopayConsentTestCase
from apps.teams.access import AccountScopedMixin, capability_for
from apps.teams.factories import ActiveMemberFactory
from apps.teams.models import TeamRole
from apps.vendors.factories import UserFactory

ID = uuid.uuid4()

OWNER = TeamRole.OWNER
ADMIN = TeamRole.ADMIN
APPROVER = TeamRole.APPROVER
ACCOUNTANT = TeamRole.MEMBER
VIEWER = TeamRole.VIEWER

ROLES = (OWNER, ADMIN, APPROVER, ACCOUNTANT, VIEWER)
PREPARERS = {OWNER, ADMIN, APPROVER, ACCOUNTANT}
APPROVERS = {OWNER, ADMIN, APPROVER}
ADMINS = {OWNER, ADMIN}

#: (method, path, roles allowed). The ask was: who can add banks, add or
#: change vendors, schedule payments, approve payments, manage the team and
#: change subscription or account settings.
MATRIX = [
    # Bills
    ("post", "/api/v1/bills/create", PREPARERS),
    ("patch", f"/api/v1/bills/{ID}/update", PREPARERS),
    ("delete", f"/api/v1/bills/{ID}/details", PREPARERS),
    ("patch", f"/api/v1/bills/occurrences/{ID}/pay", PREPARERS),
    ("post", "/api/v1/banking/scans", PREPARERS),
    ("post", f"/api/v1/banking/scans/{ID}/import", PREPARERS),
    # Vendors: adding one is preparing; repointing a known one's money is not
    ("post", "/api/v1/vendors", PREPARERS),
    ("patch", f"/api/v1/vendors/{ID}", PREPARERS),
    ("delete", f"/api/v1/vendors/{ID}", PREPARERS),
    ("post", f"/api/v1/vendors/{ID}/restore", PREPARERS),
    ("post", f"/api/v1/vendors/{ID}/payment-methods", ADMINS),
    ("patch", f"/api/v1/vendors/{ID}/payment-methods/{ID}", ADMINS),
    ("delete", f"/api/v1/vendors/{ID}/payment-methods/{ID}", ADMINS),
    ("post", f"/api/v1/vendors/{ID}/payment-methods/{ID}/set-primary", ADMINS),
    # Scheduling payments
    ("post", "/api/v1/payments", PREPARERS),
    ("patch", f"/api/v1/payments/{ID}", PREPARERS),
    ("post", f"/api/v1/payments/{ID}/cancel", PREPARERS),
    ("post", f"/api/v1/payments/batches/{ID}/cancel", PREPARERS),
    ("post", f"/api/v1/payments/{ID}/resolve", PREPARERS),
    # Approving payments
    ("post", f"/api/v1/payments/{ID}/confirm", APPROVERS),
    ("post", f"/api/v1/payments/batches/{ID}/confirm", APPROVERS),
    # Banks
    ("post", "/api/v1/banking/link/token", ADMINS),
    ("post", "/api/v1/banking/link/exchange", ADMINS),
    ("delete", f"/api/v1/banking/connections/{ID}", ADMINS),
    ("post", "/api/v1/banking/accounts", ADMINS),
    ("post", "/api/v1/users/onboarding/skip-bank", ADMINS),
    # Team
    ("post", "/api/v1/teams/invite", ADMINS),
    ("patch", f"/api/v1/teams/members/{ID}", ADMINS),
    ("delete", f"/api/v1/teams/members/{ID}", ADMINS),
    ("post", "/api/v1/teams/entities", ADMINS),
    # Subscription and account settings
    ("post", "/api/v1/billing/subscription", {OWNER}),
    ("patch", "/api/v1/billing/subscription", {OWNER}),
    ("delete", "/api/v1/billing/subscription", {OWNER}),
    ("post", "/api/v1/billing/payment-method", {OWNER}),
    ("patch", "/api/v1/users/profile", {OWNER}),
]

#: Reads every role keeps, Viewer included.
READS = [
    "/api/v1/bills",
    "/api/v1/vendors",
    "/api/v1/banking/accounts",
    "/api/v1/teams/members",
    "/api/v1/billing/subscription",
    "/api/v1/users/profile",
]


def role_forbidden(response):
    return (
        response.status_code == 403
        and response.data.get("code") == "role_forbidden"
    )


class RoleMatrixTests(TestCase):

    def setUp(self):
        self.owner = UserFactory()
        self.clients = {OWNER: self.client_for(self.owner)}

        for role in ROLES[1:]:
            member = ActiveMemberFactory(account=self.owner, role=role)
            self.clients[role] = self.client_for(member.user)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_each_role_is_allowed_exactly_its_actions(self):
        for method, path, allowed in MATRIX:
            for role in ROLES:
                with self.subTest(role=role, action=f"{method.upper()} {path}"):
                    response = getattr(self.clients[role], method)(
                        path, {}, format="json"
                    )

                    self.assertEqual(
                        role_forbidden(response),
                        role not in allowed,
                        f"{response.status_code} {response.data}",
                    )

    def test_a_refusal_names_the_missing_capability(self):
        response = self.clients[ACCOUNTANT].post(
            f"/api/v1/vendors/{ID}/payment-methods", {}, format="json"
        )

        self.assertEqual(
            response.data["capability"], "manage_vendor_payment_details"
        )

    def test_every_role_can_read(self):
        for path in READS:
            for role in ROLES:
                with self.subTest(role=role, path=path):
                    response = self.clients[role].get(path)

                    self.assertEqual(response.status_code, 200)

    def test_my_role_tells_the_viewer_it_can_change_nothing(self):
        response = self.clients[VIEWER].get("/api/v1/teams/me")

        self.assertEqual(response.data["data"]["role"], "VIEWER")
        self.assertEqual(response.data["data"]["capabilities"], ["view"])


class InviteRoleTests(TestCase):

    def setUp(self):
        self.owner = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def test_every_role_but_owner_can_be_invited(self):
        for role in ("ADMIN", "APPROVER", "MEMBER", "VIEWER"):
            with self.subTest(role=role):
                response = self.client.post(
                    "/api/v1/teams/invite",
                    {"email": f"{role.lower()}@example.com", "role": role},
                    format="json",
                )

                self.assertEqual(response.status_code, 201, response.data)
                self.assertEqual(response.data["data"]["role"], role)

    def test_member_is_labelled_accountant(self):
        self.assertEqual(TeamRole.MEMBER.label, "Accountant")

    def test_a_role_can_be_changed_to_approver(self):
        member = ActiveMemberFactory(account=self.owner, role=TeamRole.MEMBER)

        response = self.client.patch(
            f"/api/v1/teams/members/{member.id}",
            {"role": "APPROVER"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        member.refresh_from_db()
        self.assertEqual(member.role, TeamRole.APPROVER)


class AutopayNeedsAnApproverTests(AutopayConsentTestCase):
    """Autopay is a standing authorization: approving every future payment
    in advance. An Accountant who may not confirm one payment must not be
    able to authorize all of them by flipping a bill to AUTO."""

    def as_role(self, role):
        member = ActiveMemberFactory(account=self.user, role=role)
        self.client.force_authenticate(user=member.user)

    def owners_bill(self, **overrides):
        return self.create(**overrides).data["data"]["id"]

    def test_an_accountant_cannot_create_an_autopay_bill(self):
        self.as_role(ACCOUNTANT)

        response = self.create(
            autopay_mode="AUTO", autopay_consent=self.consent()
        )

        self.assertTrue(role_forbidden(response))
        self.assertEqual(response.data["capability"], "send_money")
        self.assertEqual(StandingAuthorization.objects.count(), 0)

    def test_an_accountant_can_create_a_reminder_bill(self):
        self.as_role(ACCOUNTANT)

        self.assertEqual(self.create().status_code, 201)

    def test_an_approver_can_create_an_autopay_bill(self):
        self.as_role(APPROVER)

        response = self.create(
            autopay_mode="AUTO", autopay_consent=self.consent()
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(StandingAuthorization.objects.count(), 1)

    def test_an_accountant_cannot_turn_autopay_on(self):
        bill_id = self.owners_bill()
        self.as_role(ACCOUNTANT)

        response = self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"autopay_mode": "AUTO", "autopay_consent": self.consent()},
            format="json",
        )

        self.assertTrue(role_forbidden(response))

    def test_an_accountant_can_edit_an_autopay_bill_without_new_terms(self):
        bill_id = self.owners_bill(
            autopay_mode="AUTO", autopay_consent=self.consent()
        )
        self.as_role(ACCOUNTANT)

        response = self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"notes": "Paid from operating"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)

    def test_an_accountant_cannot_agree_to_new_autopay_terms(self):
        bill_id = self.owners_bill(
            autopay_mode="AUTO", autopay_consent=self.consent()
        )
        self.as_role(ACCOUNTANT)

        response = self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"amount": "1.00", "autopay_consent": self.consent()},
            format="json",
        )

        self.assertTrue(role_forbidden(response))

    def test_an_accountant_can_turn_autopay_off(self):
        bill_id = self.owners_bill(
            autopay_mode="AUTO", autopay_consent=self.consent()
        )
        self.as_role(ACCOUNTANT)

        response = self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"autopay_mode": "REMIND"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)


#: Account-scoped writes that need no capability, and why.
UNGATED_WRITES = {
    # Reads that happen to be POSTs: nothing is saved.
    "PaymentQuoteAPIView": "prices a payment, saves nothing",
    "AutopayAuthorizationPreviewAPIView": "returns text, saves nothing",
    "BillQRDecodeAPIView": "decodes an image, saves nothing",
}


def _views():
    def walk(patterns):
        for pattern in patterns:
            if hasattr(pattern, "url_patterns"):
                yield from walk(pattern.url_patterns)
            else:
                yield getattr(pattern.callback, "view_class", None)

    return {view for view in walk(get_resolver().url_patterns) if view}


class EveryWriteIsGatedTests(TestCase):

    def test_no_account_scoped_write_is_open_to_every_role(self):
        """A write a Viewer can make is a write nobody decided about."""
        open_writes = [
            f"{view.__name__} {method}"
            for view in _views()
            if issubclass(view, AccountScopedMixin)
            and view.__name__ not in UNGATED_WRITES
            for method in ("POST", "PUT", "PATCH", "DELETE")
            if hasattr(view, method.lower())
            and capability_for(view, method) is None
        ]

        self.assertEqual(sorted(open_writes), [])
