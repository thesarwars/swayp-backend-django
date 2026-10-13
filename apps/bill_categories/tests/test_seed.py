"""The seeded categories are a client contract (BILLS-9).

Nothing created these rows before 0003, so a freshly migrated database served
an empty ``GET /bill-categories``: Home's "Bill Types" row drew nothing and
``POST /bills/create``, which requires a category, could not succeed at all.

``display_order`` is the part the client is pinned to — the mobile app keys
its four hand-drawn badges to orders 1-4, not to the names — so reordering
the first four silently puts the wrong drawing on a category.
"""

from django.test import TestCase

from apps.bill_categories.models import BillCategory
from apps.bill_categories.selectors.default_category import default_category


class SeededCategoryTests(TestCase):

    def test_a_migrated_database_has_categories(self):
        self.assertTrue(BillCategory.objects.exists())

    def test_the_first_four_orders_are_the_drawn_utilities(self):
        """The app's ARTWORK_BY_DISPLAY_ORDER map: 1 electricity, 2 gas,
        3 water, 4 internet. Changing these reassigns the drawings."""
        first_four = list(
            BillCategory.objects.filter(display_order__lte=4)
            .order_by("display_order")
            .values_list("display_order", "name")
        )

        self.assertEqual(
            first_four,
            [(1, "Electricity"), (2, "Gas"), (3, "Water"), (4, "Internet")],
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
