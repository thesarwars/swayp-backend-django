"""DASH-1 — GET notifications filtered on the server.

The chips on the notifications screen used to filter on the client, so an
empty chip could not be told apart from "the matches are on a later page".
Every filter here is applied before pagination, which is the whole point.
"""

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.common.enums import NOTIFICATION_CATEGORY_TYPES, NotificationType
from apps.notifications.factories import NotificationFactory
from apps.vendors.factories import UserFactory

LIST_URL = "/api/v1/notifications"


class NotificationListFilterTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _get(self, query=""):
        return self.client.get(f"{LIST_URL}{query}")

    def _types(self, response):
        return sorted(row["type"] for row in response.json()["data"])

    def test_no_filters_returns_everything_read_and_unread(self):
        NotificationFactory(user=self.user, is_read=True)
        NotificationFactory(user=self.user, is_read=False)

        response = self._get()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["data"]), 2)

    def test_type_is_repeatable(self):
        NotificationFactory(user=self.user, type=NotificationType.BILL_DUE)
        NotificationFactory(user=self.user, type=NotificationType.PAYMENT_FAILED)
        NotificationFactory(user=self.user, type=NotificationType.PROMOTION)

        response = self._get("?type=BILL_DUE&type=PAYMENT_FAILED")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._types(response), ["BILL_DUE", "PAYMENT_FAILED"])

    def test_unknown_type_is_a_400(self):
        response = self._get("?type=NOPE")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_category_transactions_excludes_promotion_and_system(self):
        NotificationFactory(user=self.user, type=NotificationType.BILL_DUE)
        NotificationFactory(user=self.user, type=NotificationType.PROMOTION)
        NotificationFactory(user=self.user, type=NotificationType.SYSTEM)

        response = self._get("?category=transactions")

        self.assertEqual(self._types(response), ["BILL_DUE"])

    def test_category_promotion(self):
        NotificationFactory(user=self.user, type=NotificationType.BILL_DUE)
        NotificationFactory(user=self.user, type=NotificationType.PROMOTION)

        response = self._get("?category=promotion")

        self.assertEqual(self._types(response), ["PROMOTION"])

    def test_unknown_category_is_a_400(self):
        response = self._get("?category=everything")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_type_and_category_intersect(self):
        NotificationFactory(user=self.user, type=NotificationType.BILL_DUE)
        NotificationFactory(user=self.user, type=NotificationType.PROMOTION)

        response = self._get("?category=transactions&type=PROMOTION")

        self.assertEqual(response.json()["data"], [])

    def test_is_read_false_returns_only_unread(self):
        NotificationFactory(user=self.user, is_read=True, title="old")
        NotificationFactory(user=self.user, is_read=False, title="new")

        response = self._get("?isRead=false")

        self.assertEqual(
            [row["title"] for row in response.json()["data"]], ["new"]
        )

    def test_filters_apply_before_pagination(self):
        # The bug in the ticket: a page of 2 sorted newest-first would hold
        # only bill reminders, and a client-side filter would see no promotion.
        NotificationFactory(user=self.user, type=NotificationType.PROMOTION)
        NotificationFactory.create_batch(
            3, user=self.user, type=NotificationType.BILL_DUE
        )

        response = self._get("?category=promotion&page=1&pageSize=2")

        body = response.json()
        self.assertEqual(self._types(response), ["PROMOTION"])
        self.assertEqual(body["pagination"]["totalItems"], 1)

    def test_other_users_rows_never_leak_through_a_filter(self):
        NotificationFactory(type=NotificationType.PROMOTION)

        response = self._get("?category=promotion")

        self.assertEqual(response.json()["data"], [])

    def test_every_type_is_placed_or_deliberately_uncategorised(self):
        placed = {t for types in NOTIFICATION_CATEGORY_TYPES.values() for t in types}
        uncategorised = {NotificationType.SYSTEM, NotificationType.SECURITY}

        self.assertEqual(placed | uncategorised, set(NotificationType))
