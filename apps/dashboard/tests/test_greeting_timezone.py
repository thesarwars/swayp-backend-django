"""Web B5: the greeting follows the viewer's time zone when they send it."""

import datetime as dt
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.dashboard.services.dashboard_service import DashboardService
from apps.vendors.factories import UserFactory

# 06:10 UTC: the tester's midday in Dhaka, the middle of the night in New York.
NOW = dt.datetime(2026, 10, 14, 6, 10, tzinfo=dt.timezone.utc)


class GreetingTests(SimpleTestCase):

    def test_the_viewers_zone_decides(self):
        greet = DashboardService._get_greeting

        self.assertEqual(greet(NOW, tz=ZoneInfo("Asia/Dhaka")), "Good Afternoon")
        self.assertEqual(greet(NOW), "Good Night")


class EndpointTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=UserFactory())

    def test_tz_is_accepted_and_validated(self):
        ok = self.client.get("/api/v1/dashboard/profile-summary?tz=Asia/Dhaka")
        bad = self.client.get("/api/v1/dashboard/profile-summary?tz=Mars/Base")

        self.assertEqual(ok.status_code, 200)
        self.assertEqual(bad.status_code, 400)
        self.assertIn("tz", bad.json()["errors"])
