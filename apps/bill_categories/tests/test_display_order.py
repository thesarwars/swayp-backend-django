"""BILLS-9: categories are identified and ordered by displayOrder, so it is
unique. 0 means "not set" and puts a new category at the end."""

from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from apps.bill_categories.models import BillCategory
from apps.vendors.factories import UserFactory


def make(name, **kwargs):
    return BillCategory.objects.create(
        name=name, icon="https://e.com/i.png", color="#111", **kwargs
    )


class DisplayOrderTests(TestCase):

    def test_an_unset_order_goes_to_the_end(self):
        first = make("Rent")
        second = make("Utilities")

        self.assertEqual((first.display_order, second.display_order), (1, 2))

    def test_an_explicit_order_is_kept(self):
        self.assertEqual(make("Rent", display_order=7).display_order, 7)

    def test_two_categories_cannot_share_an_order(self):
        make("Rent", display_order=3)

        with self.assertRaises(IntegrityError), transaction.atomic():
            make("Utilities", display_order=3)

    def test_the_api_lists_them_by_display_order(self):
        make("Zeta", display_order=1)
        make("Alpha", display_order=2)
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        rows = client.get("/api/v1/bill-categories").json()["data"]

        self.assertEqual([r["name"] for r in rows[:2]], ["Zeta", "Alpha"])
        self.assertEqual([r["displayOrder"] for r in rows[:2]], [1, 2])
