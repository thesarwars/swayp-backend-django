"""API-5: snake_case beside the shipped camelCase, in and out."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.casing import to_snake, with_snake_case
from apps.notifications.factories import NotificationFactory
from apps.vendors.factories import UserFactory


class HelperTests(TestCase):

    def test_to_snake(self):
        self.assertEqual(to_snake("unreadNotificationCount"),
                         "unread_notification_count")
        self.assertEqual(to_snake("page"), "page")

    def test_mirror_keeps_existing_keys_and_is_shallow(self):
        self.assertEqual(
            with_snake_case({"isRead": True, "metadata": {"billId": 1}}),
            {"isRead": True, "is_read": True, "metadata": {"billId": 1}},
        )


class EndpointTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        NotificationFactory.create_batch(3, user=self.user)

    def test_notifications_carry_both_spellings(self):
        body = self.client.get("/api/v1/notifications?pageSize=2").json()

        self.assertEqual(body["unread_count"], body["unreadCount"])
        self.assertIn("next_cursor", body)
        self.assertEqual(body["pagination"]["page_size"], 2)
        row = body["data"][0]
        self.assertEqual(row["is_read"], row["isRead"])
        self.assertEqual(row["created_at"], row["createdAt"])

    def test_query_params_accept_snake_case(self):
        body = self.client.get(
            "/api/v1/notifications?page_size=1&is_read=true"
        ).json()

        self.assertEqual(body["data"], [])
        self.assertEqual(body["pagination"]["pageSize"], 1)

    def test_camel_case_wins_when_both_are_sent(self):
        body = self.client.get(
            "/api/v1/notifications?pageSize=2&page_size=1"
        ).json()

        self.assertEqual(len(body["data"]), 2)

    def test_read_all_mirrors_marked_count(self):
        data = self.client.patch("/api/v1/notifications/read-all").json()[
            "data"
        ]

        self.assertEqual(data["marked_count"], 3)
        self.assertEqual(data["markedCount"], 3)

    def test_payment_history_rows_mirror(self):
        from apps.payments.factories import PaymentFactory

        PaymentFactory(user=self.user)

        row = self.client.get("/api/v1/payments/history").json()["data"][0]

        self.assertEqual(row["vendor_name"], row["vendorName"])
        self.assertEqual(row["transaction_reference"],
                         row["transactionReference"])
