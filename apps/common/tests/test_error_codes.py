"""API-3: every error carries a stable code, so the app branches on it
rather than on the wording of the message."""

import datetime as dt
import uuid

from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.common.exception_handler import custom_exception_handler
from apps.payments.tests.test_payment_flow import PayFlowTestCase
from apps.vendors.factories import UserFactory


class GenericCodeTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_no_token_is_not_authenticated(self):
        body = self.client.get("/api/v1/billing/subscription").json()

        self.assertEqual(body["code"], "not_authenticated")

    def test_a_bad_token_says_refresh(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")

        body = self.client.get("/api/v1/billing/subscription").json()

        self.assertEqual(body["code"], "token_not_valid")

    def test_not_found_and_validation(self):
        self.client.force_authenticate(user=UserFactory())

        missing = self.client.get(f"/api/v1/payments/{uuid.uuid4()}").json()
        invalid = self.client.post(
            "/api/v1/billing/subscription", {"plan": "NOPE"}, format="json"
        ).json()

        self.assertEqual(missing["code"], "not_found")
        self.assertEqual(invalid["code"], "validation_failed")

    def test_a_list_validation_error_is_enveloped_too(self):
        body = custom_exception_handler(ValidationError(["Nope."]), {}).data

        self.assertEqual(
            body,
            {"success": False, "message": "Nope.",
             "code": "validation_failed"},
        )


class SpecificCodeTests(PayFlowTestCase):

    URL = "/api/v1/payments"

    def test_no_funding_account(self):
        self.account.is_default_funding_source = False
        self.account.save(update_fields=["is_default_funding_source"])

        response = self.client.post(
            self.URL,
            {"occurrence_ids": [str(self.occurrence().id)]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "no_funding_account")
        self.assertIn("funding_account_id", response.json()["errors"])

    def test_an_idempotency_key_reused_with_another_body(self):
        first, second = self.occurrence(), self.occurrence(
            due_date=dt.date(2026, 10, 1)
        )
        headers = {"HTTP_IDEMPOTENCY_KEY": "k-1"}

        self.client.post(
            self.URL, {"occurrence_ids": [str(first.id)]}, format="json",
            **headers,
        )
        response = self.client.post(
            self.URL, {"occurrence_ids": [str(second.id)]}, format="json",
            **headers,
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "idempotency_key_reused")
