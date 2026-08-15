"""E8-S3 — the feature-package migration changed no URL and no response.

Every path and route name is copied byte-for-byte from the flat layout, so a
missed include is an ImportError on every request rather than a silent 404,
and this file is what catches it. The one deliberate response change is
additive: `metadata`, without which the deep-link payload the epic requires is
write-only.
"""

from io import StringIO

from django.core.management import call_command
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.common.enums import NotificationType
from apps.notifications.factories import NotificationFactory
from apps.vendors.factories import UserFactory

NOTIFICATION_FIELDS = {
    "id",
    "title",
    "message",
    "type",
    "isRead",
    "createdAt",
    "readAt",
    "metadata",
}


class NotificationLayoutTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_notification_urls_are_unchanged_after_the_restructure(self):
        notification = NotificationFactory(user=self.user)

        self.assertEqual(
            reverse("notification-list"), "/api/v1/notifications"
        )
        self.assertEqual(
            reverse("notification-read", args=[notification.id]),
            f"/api/v1/notifications/{notification.id}/read",
        )
        self.assertEqual(
            reverse("notification-read-all"),
            "/api/v1/notifications/read-all",
        )
        self.assertEqual(
            reverse("notification-preferences"),
            "/api/v1/notifications/preferences",
        )

    def test_notification_list_response_fields_are_unchanged(self):
        NotificationFactory(user=self.user)

        response = self.client.get(reverse("notification-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        body = response.json()
        self.assertTrue(body["success"])
        self.assertIn("pagination", body)
        self.assertEqual(set(body["data"][0]), NOTIFICATION_FIELDS)

    def test_notification_list_carries_the_deep_link_payload(self):
        NotificationFactory(
            user=self.user,
            type=NotificationType.BILL_DUE,
            metadata={"bill_id": "b1", "occurrence_id": "o1"},
        )

        row = self.client.get(reverse("notification-list")).json()["data"][0]

        self.assertEqual(row["metadata"]["bill_id"], "b1")
        self.assertEqual(row["metadata"]["occurrence_id"], "o1")

    def test_marking_read_still_works_through_the_moved_view(self):
        notification = NotificationFactory(user=self.user)

        response = self.client.patch(
            reverse("notification-read", args=[notification.id])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_no_pending_migrations(self):
        call_command(
            "makemigrations",
            "notifications",
            "--check",
            "--dry-run",
            stdout=StringIO(),
        )

    def test_the_preference_migration_keeps_the_name_e8_s4_depends_on(self):
        """E8-S4's 0004 declares a dependency on this exact node name."""
        loader = MigrationLoader(None, ignore_no_migrations=True)

        self.assertIn(
            (
                "notifications",
                "0003_notificationpreference_alter_notification_type",
            ),
            loader.graph.nodes,
        )
