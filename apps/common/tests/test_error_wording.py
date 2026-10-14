"""Web C6: no framework wording and no bare {detail} reaches a client."""

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.exception_handler import _not_found_text
from apps.vendors.factories import UserFactory


class ErrorWordingTests(TestCase):

    def test_django_404_text_reads_like_the_rest(self):
        self.assertEqual(
            _not_found_text("No Vendor matches the given query."),
            "Vendor not found.",
        )
        self.assertEqual(
            _not_found_text("No VendorPaymentMethod matches the given query."),
            "Vendor payment method not found.",
        )
        self.assertEqual(_not_found_text("Bill not found."), "Bill not found.")

    def test_an_unknown_vendor(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        body = client.get(f"/api/v1/vendors/{uuid.uuid4()}").json()

        self.assertEqual(body["message"], "Vendor not found.")
        self.assertEqual(body["code"], "not_found")

    def test_a_webhook_without_a_signature_is_enveloped(self):
        body = APIClient().post(
            "/webhooks/mock", {"id": "evt"}, format="json"
        ).json()

        self.assertEqual(body["success"], False)
        self.assertEqual(body["code"], "invalid_signature")
        self.assertNotIn("detail", body)
