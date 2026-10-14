"""Web S1: the status-change routes are staff-only and not published."""

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.tests.openapi_contract import published_schema
from apps.payments.factories import PaymentFactory
from apps.vendors.factories import UserFactory


class StaffStatusRouteTests(TestCase):

    def test_a_customer_is_refused_before_any_lookup(self):
        user = UserFactory()
        payment = PaymentFactory(user=user)
        client = APIClient()
        client.force_authenticate(user=user)

        for action in ("successful", "processing", "failed"):
            for pid in (payment.id, uuid.uuid4()):
                with self.subTest(action=action, own=pid == payment.id):
                    response = client.patch(
                        f"/api/v1/payments/{pid}/{action}", {}, format="json"
                    )
                    self.assertEqual(response.status_code, 403)

    def test_they_are_not_in_the_client_schema(self):
        paths = published_schema()["paths"]

        for action in ("successful", "processing", "failed"):
            with self.subTest(action=action):
                self.assertNotIn(f"/api/v1/payments/{{payment_id}}/{action}", paths)
