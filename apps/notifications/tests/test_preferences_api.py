"""E8-S3 — GET/PATCH notifications/preferences/.

Two properties carry the story. Reading never writes: a type the user has
never touched comes back at its defaults with isDefault=true and no row, so
changing a default later still reaches them. And a channel with no delivery
adapter cannot be switched on — the API refuses it rather than storing a
promise the product cannot keep (BRD §1.2).
"""

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.common.enums import NotificationType
from apps.notifications.models import NotificationPreference
from apps.vendors.factories import UserFactory

PREFERENCES_URL = "/api/v1/notifications/preferences/"


class NotificationPreferencesAPITests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _entry(self, payload, notification_type):
        return next(
            row
            for row in payload["data"]["preferences"]
            if row["type"] == notification_type
        )

    def test_get_returns_every_type_without_creating_a_row(self):
        response = self.client.get(PREFERENCES_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        preferences = response.json()["data"]["preferences"]

        self.assertEqual(
            [row["type"] for row in preferences], NotificationType.values
        )
        self.assertTrue(all(row["isDefault"] for row in preferences))
        self.assertTrue(all(row["inApp"] for row in preferences))
        self.assertTrue(all(row["email"] for row in preferences))
        self.assertFalse(any(row["sms"] for row in preferences))
        self.assertFalse(any(row["push"] for row in preferences))

        self.assertEqual(NotificationPreference.objects.count(), 0)

    def test_patch_creates_a_row_only_for_the_type_it_names(self):
        response = self.client.patch(
            PREFERENCES_URL,
            {
                "preferences": [
                    {"type": NotificationType.BILL_DUE, "email": False}
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        row = NotificationPreference.objects.get()
        self.assertEqual(row.type, NotificationType.BILL_DUE)
        self.assertFalse(row.email)
        # Untouched channels take the column default on insert.
        self.assertTrue(row.in_app)

        payload = response.json()
        bill_due = self._entry(payload, NotificationType.BILL_DUE)

        self.assertFalse(bill_due["isDefault"])
        self.assertFalse(bill_due["email"])
        self.assertTrue(bill_due["inApp"])
        self.assertTrue(
            all(
                row["isDefault"]
                for row in payload["data"]["preferences"]
                if row["type"] != NotificationType.BILL_DUE
            )
        )

    def test_patch_rejects_an_unknown_type(self):
        response = self.client.patch(
            PREFERENCES_URL,
            {"preferences": [{"type": "WIDGET", "email": False}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["message"], "Validation failed.")
        self.assertIn("preferences", body["errors"])

        self.assertEqual(NotificationPreference.objects.count(), 0)

    def test_patch_leaves_unnamed_channels_and_types_untouched(self):
        self.client.patch(
            PREFERENCES_URL,
            {
                "preferences": [
                    {"type": NotificationType.BILL_DUE, "inApp": False}
                ]
            },
            format="json",
        )
        self.client.patch(
            PREFERENCES_URL,
            {
                "preferences": [
                    {"type": NotificationType.BILL_DUE, "email": False}
                ]
            },
            format="json",
        )

        row = NotificationPreference.objects.get(
            type=NotificationType.BILL_DUE
        )
        self.assertFalse(row.in_app)
        self.assertFalse(row.email)

        self.assertFalse(
            NotificationPreference.objects.filter(
                type=NotificationType.PAYMENT_FAILED
            ).exists()
        )

    def test_patch_refuses_to_switch_on_a_channel_with_no_adapter(self):
        refused = self.client.patch(
            PREFERENCES_URL,
            {
                "preferences": [
                    {"type": NotificationType.BILL_DUE, "sms": True}
                ]
            },
            format="json",
        )

        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(NotificationPreference.objects.count(), 0)

        # A client may still send its whole state back — sms/push off is fine
        # alongside a channel that can actually change.
        accepted = self.client.patch(
            PREFERENCES_URL,
            {
                "preferences": [
                    {
                        "type": NotificationType.BILL_DUE,
                        "inApp": True,
                        "email": False,
                        "sms": False,
                        "push": False,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(accepted.status_code, status.HTTP_200_OK)
        self.assertFalse(
            NotificationPreference.objects.get(
                type=NotificationType.BILL_DUE
            ).email
        )

        channels = {
            row["key"]: row
            for row in self.client.get(PREFERENCES_URL).json()["data"][
                "channels"
            ]
        }

        self.assertTrue(channels["inApp"]["supported"])
        self.assertTrue(channels["inApp"]["enabled"])
        # Supported and enabled are different facts: email has an adapter and
        # a release gate, SMS has neither.
        self.assertTrue(channels["email"]["supported"])
        self.assertFalse(channels["email"]["enabled"])
        self.assertFalse(channels["sms"]["supported"])
        self.assertFalse(channels["push"]["supported"])

    def test_patch_rejects_the_same_type_twice_in_one_payload(self):
        response = self.client.patch(
            PREFERENCES_URL,
            {
                "preferences": [
                    {"type": NotificationType.BILL_DUE, "email": False},
                    {"type": NotificationType.BILL_DUE, "email": True},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(NotificationPreference.objects.count(), 0)

    def test_patch_rejects_an_item_naming_no_channel(self):
        response = self.client.patch(
            PREFERENCES_URL,
            {"preferences": [{"type": NotificationType.BILL_DUE}]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(NotificationPreference.objects.count(), 0)

    def test_patch_rejects_an_item_that_could_not_change_anything(self):
        """sms/push-only is the same request as naming no channel at all.

        Both can only ever be false, so nothing the user can perceive would
        change — but the upsert would still write a row, which flips
        isDefault to false for that type forever and pins inApp and email to
        whatever the defaults happen to be today. That is precisely the
        outcome the never-writes-on-read design exists to prevent, arrived at
        through the back door.
        """
        for payload in ({"sms": False}, {"push": False}):
            with self.subTest(payload=payload):
                response = self.client.patch(
                    PREFERENCES_URL,
                    {
                        "preferences": [
                            {"type": NotificationType.BILL_DUE, **payload}
                        ]
                    },
                    format="json",
                )

                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST
                )
                self.assertEqual(NotificationPreference.objects.count(), 0)

        # The type is still untouched, so a later change to its defaults
        # still reaches this user.
        bill_due = self._entry(
            self.client.get(PREFERENCES_URL).json(),
            NotificationType.BILL_DUE,
        )

        self.assertTrue(bill_due["isDefault"])

    def test_preferences_are_scoped_to_the_requesting_user(self):
        other = UserFactory()
        NotificationPreference.objects.create(
            user=other, type=NotificationType.BILL_DUE, email=False
        )

        payload = self.client.get(PREFERENCES_URL).json()

        self.assertTrue(
            self._entry(payload, NotificationType.BILL_DUE)["isDefault"]
        )
        self.assertTrue(
            self._entry(payload, NotificationType.BILL_DUE)["email"]
        )

    def test_preferences_endpoint_requires_authentication(self):
        anonymous = APIClient()

        self.assertEqual(
            anonymous.get(PREFERENCES_URL).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertEqual(
            anonymous.patch(
                PREFERENCES_URL,
                {
                    "preferences": [
                        {"type": NotificationType.BILL_DUE, "email": False}
                    ]
                },
                format="json",
            ).status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
