"""Web C2: answers that still carry camelCase copies announce when they go;
answers without them don't."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.notifications.factories import NotificationFactory
from apps.vendors.factories import UserFactory


class SunsetHeaderTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_camel_case_answers_carry_the_headers(self):
        NotificationFactory(user=self.user)

        for url in ("/api/v1/notifications", "/api/v1/dashboard/profile-summary",
                    "/api/v1/vendors"):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response["Sunset"], "Sun, 15 Nov 2026 00:00:00 GMT")
                self.assertTrue(response["Deprecation"].startswith("@"))

    def test_snake_case_answers_do_not(self):
        response = self.client.get("/api/v1/billing/plans")

        self.assertNotIn("Sunset", response)
        self.assertNotIn("Deprecation", response)
