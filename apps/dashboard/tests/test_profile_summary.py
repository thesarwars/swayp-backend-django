"""E8-S1 — regression lock on GET dashboard/profile-summary/.

The endpoint moved into the feature-package layout in the same change that
added dashboard/home/, so its URL, route name, envelope and camelCase field
names are pinned here: the restructure is only safe if nothing on the wire
moved with it. The greeting fix is the one intended behaviour change.
"""

import datetime as dt

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.dashboard.services.dashboard_service import DashboardService
from apps.vendors.factories import UserFactory

PROFILE_SUMMARY_URL = "/api/v1/dashboard/profile-summary"


class ProfileSummaryAPITests(TestCase):

    def setUp(self):
        self.user = UserFactory(first_name="Jhon", last_name="Doe")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_profile_summary_keeps_its_url_and_route_name(self):
        self.assertEqual(
            reverse("dashboard-profile-summary"), PROFILE_SUMMARY_URL
        )

        response = self.client.get(PROFILE_SUMMARY_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_profile_summary_response_keys_are_unchanged_camel_case(self):
        response = self.client.get(PROFILE_SUMMARY_URL)

        self.assertEqual(
            set(response.data["data"].keys()),
            {
                "id",
                "fullName",
                "profilePicture",
                "greeting",
                "unreadNotificationCount",
            },
        )
        self.assertEqual(response.data["data"]["fullName"], "Jhon Doe")
        self.assertIsNone(response.data["data"]["profilePicture"])
        self.assertEqual(response.data["data"]["unreadNotificationCount"], 0)

    def test_profile_summary_envelope_is_unchanged(self):
        response = self.client.get(PROFILE_SUMMARY_URL)

        self.assertIs(response.data["success"], True)
        self.assertIn("data", response.data)
        # The view passes no message, so the ApiResponse default stands.
        self.assertEqual(response.data["message"], "Success")


class GreetingTests(SimpleTestCase):
    """The greeting has to read the user's clock, not the server's."""

    @staticmethod
    def _utc(hour, minute=0):
        return dt.datetime(
            2026, 7, 29, hour, minute, tzinfo=dt.timezone.utc
        )

    def test_greeting_follows_eastern_not_utc(self):
        # 23:30 UTC is 19:30 Eastern. Under timezone.localtime() this said
        # "Good Night"; under Eastern it is still evening.
        self.assertEqual(
            DashboardService._get_greeting(now=self._utc(23, 30)),
            "Good Evening",
        )

        # 12:00 UTC is 08:00 Eastern — morning, not afternoon.
        self.assertEqual(
            DashboardService._get_greeting(now=self._utc(12)),
            "Good Morning",
        )

    def test_greeting_bands_are_unchanged(self):
        # Eastern hours 08 / 14 / 19 / 02 (July, so UTC-4).
        self.assertEqual(
            DashboardService._get_greeting(now=self._utc(12)), "Good Morning"
        )
        self.assertEqual(
            DashboardService._get_greeting(now=self._utc(18)),
            "Good Afternoon",
        )
        self.assertEqual(
            DashboardService._get_greeting(now=self._utc(23)), "Good Evening"
        )
        self.assertEqual(
            DashboardService._get_greeting(now=self._utc(6)), "Good Night"
        )
