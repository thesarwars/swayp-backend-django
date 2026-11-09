"""The seeded categories are a client contract (BILLS-9).

Nothing created these rows before 0003, so a freshly migrated database served
an empty ``GET /bill-categories``: Home's "Bill Types" row drew nothing and
``POST /bills/create``, which requires a category, could not succeed at all.

Migration 0005 replaced the seeded list with the agreed one and its order.
"""

from django.test import TestCase

from apps.bill_categories.models import BillCategory
from apps.bill_categories.selectors.default_category import default_category


class SeededCategoryTests(TestCase):

    def test_a_migrated_database_has_categories(self):
        self.assertTrue(BillCategory.objects.exists())

    def test_the_first_four_orders_follow_the_agreed_list(self):
        first_four = list(
            BillCategory.objects.filter(display_order__lte=4)
            .order_by("display_order")
            .values_list("display_order", "name")
        )

        self.assertEqual(
            first_four,
            [
                (1, "Advertising & Marketing"),
                (2, "Bank & Financial Fees"),
                (3, "Credit Cards"),
                (4, "Equipment"),
            ],
        )

    def test_every_category_is_active_and_coloured(self):
        """An inactive category is invisible to the API, and the client tints
        the plain badge with ``color`` for anything past the first four."""
        for category in BillCategory.objects.all():
            with self.subTest(category=category.name):
                self.assertTrue(category.is_active)
                self.assertRegex(category.color, r"^#[0-9A-Fa-f]{6}$")

    def test_the_default_category_resolves(self):
        """``default_category()`` files a vendor created without one. It looks
        for "Other" by name, so the seed has to provide it."""
        self.assertEqual(default_category().name, "Other")

    def test_display_order_is_unique(self):
        orders = list(
            BillCategory.objects.values_list("display_order", flat=True)
        )

        self.assertEqual(len(orders), len(set(orders)))


class OptionalIconTests(TestCase):
    """A category can be created without an icon, and the list then sends
    an empty string for it."""

    def test_a_category_without_an_icon(self):
        from rest_framework.test import APIClient

        from apps.bill_categories.models import BillCategory
        from apps.vendors.factories import UserFactory

        category = BillCategory.objects.create(name="Uncharted", color="#000")
        category.full_clean()

        client = APIClient()
        client.force_authenticate(user=UserFactory())
        rows = client.get("/api/v1/bill-categories").json()["data"]
        row = next(r for r in rows if r["name"] == "Uncharted")

        self.assertEqual(row["icon"], "")
