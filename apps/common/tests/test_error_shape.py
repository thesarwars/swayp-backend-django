"""API-4: one error shape everywhere.

{ success: false, message, errors?: { field: [string] } }, JSON for every
error under /api/ (unknown routes included), and 404 when the id in the URL
is not the caller's.
"""

import uuid

from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.common.exception_handler import custom_exception_handler
from apps.vendors.factories import UserFactory
from rest_framework.test import APIClient


class ErrorValuesAreListsTests(TestCase):

    def _errors(self, detail):
        return custom_exception_handler(ValidationError(detail), {}).data[
            "errors"
        ]

    def test_a_bare_string_becomes_a_list(self):
        self.assertEqual(
            self._errors({"subscription": "No active subscription."}),
            {"subscription": ["No active subscription."]},
        )

    def test_lists_stay_lists_and_nesting_is_kept(self):
        self.assertEqual(
            self._errors(
                {
                    "plan": ["Required."],
                    "payment_method": {"routing_number": "Invalid."},
                }
            ),
            {
                "plan": ["Required."],
                "payment_method": {"routing_number": ["Invalid."]},
            },
        )

    def test_per_item_errors_keep_their_positions(self):
        self.assertEqual(
            self._errors({"items": [{}, {"amount": "Too big."}]}),
            {"items": [{}, {"amount": ["Too big."]}]},
        )


class JsonEverywhereTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=UserFactory())

    def test_an_unknown_route_is_a_json_404(self):
        response = self.client.get("/api/v1/no-such-thing")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(
            response.json(),
            {"success": False, "message": "Not found.", "code": "not_found"},
        )

    def test_a_service_error_reaches_the_client_as_a_list(self):
        response = self.client.get("/api/v1/billing/fees")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["errors"],
            {"subscription": ["No active subscription."]},
        )

    def test_outside_the_api_nothing_changes(self):
        response = self.client.get("/no-such-page")

        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(response.get("Content-Type"), "application/json")


class SomeoneElsesIdIs404Tests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=UserFactory())

    def test_ids_in_the_url_that_are_not_yours_are_404(self):
        missing = uuid.uuid4()

        for method, url in [
            ("get", f"/api/v1/payments/{missing}"),
            ("get", f"/api/v1/payments/{missing}/status"),
            ("post", f"/api/v1/payments/{missing}/cancel"),
            ("get", f"/api/v1/payments/batches/{missing}/status"),
            ("get", f"/api/v1/banking/connections/{missing}"),
            ("delete", f"/api/v1/banking/connections/{missing}"),
            ("get", f"/api/v1/banking/scans/{missing}"),
        ]:
            with self.subTest(url=url, method=method):
                response = getattr(self.client, method)(url)

                self.assertEqual(response.status_code, 404)
                self.assertFalse(response.json()["success"])

    def test_an_unknown_id_in_the_body_is_still_a_400(self):
        response = self.client.post(
            "/api/v1/banking/scans",
            {"connection_id": str(uuid.uuid4())},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("connection", response.json()["errors"])
