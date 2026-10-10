"""API-1: the published schema matches what the server sends.

Each test calls a real endpoint and validates the body against the schema
published for it. Add the endpoint here when you add or change one.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.tests.openapi_contract import assert_matches_schema
from apps.vendors.factories import UserFactory


class ContractTestCase(TestCase):

    def setUp(self):
        self.user = UserFactory(is_active=True, is_verified=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def check(self, method, url, path=None, body=None, status=None):
        response = getattr(self.client, method.lower())(
            url, body, format="json"
        ) if body is not None else getattr(self.client, method.lower())(url)

        if status is not None:
            self.assertEqual(response.status_code, status, response.content)

        assert_matches_schema(self, response, method, path or url)

        return response


class ErrorContractTests(ContractTestCase):

    def test_validation_error(self):
        self.check("POST", "/api/v1/billing/subscription",
                   body={"plan": "NOPE"}, status=400)

    def test_not_found(self):
        self.check(
            "GET", "/api/v1/payments/00000000-0000-0000-0000-000000000000",
            path="/api/v1/payments/{payment_id}", status=404,
        )

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)

        self.check("GET", "/api/v1/billing/subscription", status=401)


class BillingContractTests(ContractTestCase):

    def subscribe(self):
        return self.check(
            "POST", "/api/v1/billing/subscription",
            body={"plan": "STANDARD"}, status=201,
        )

    def test_plans(self):
        self.check("GET", "/api/v1/billing/plans", status=200)

    def test_subscription_lifecycle(self):
        self.check("GET", "/api/v1/billing/subscription", status=200)
        self.subscribe()
        self.check("GET", "/api/v1/billing/subscription", status=200)
        self.check("PATCH", "/api/v1/billing/subscription",
                   body={"plan": "ENTERPRISE"}, status=200)
        self.check("DELETE", "/api/v1/billing/subscription", status=200)
        self.check("POST", "/api/v1/billing/subscription/resume", status=200)

    def test_reads(self):
        self.subscribe()

        for url in ("/api/v1/billing/allowances", "/api/v1/billing/invoice",
                    "/api/v1/billing/fees", "/api/v1/billing/invoices",
                    "/api/v1/billing/config", "/api/v1/billing/addons",
                    "/api/v1/billing/payment-method"):
            with self.subTest(url=url):
                self.check("GET", url, status=200)

    def test_addons(self):
        self.check("POST", "/api/v1/billing/subscription",
                   body={"plan": "ENTERPRISE"}, status=201)

        self.check("POST", "/api/v1/billing/addons",
                   body={"kind": "ERP_SYNC", "quantity": 1}, status=200)
        self.check("POST", "/api/v1/billing/addons",
                   body={"kind": "ERP_SYNC", "quantity": 0}, status=200)
