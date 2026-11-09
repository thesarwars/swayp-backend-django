"""The agreed category list: its order, and renames keeping their links."""

import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from apps.bill_categories.models import BillCategory
from apps.vendors.factories import UserFactory
from apps.vendors.models import Vendor

migration = importlib.import_module(
    "apps.bill_categories.migrations.0005_category_list_rename_and_order"
)
NAMES = [name for name, _ in migration.CATEGORIES]


class CategoryListTests(TestCase):

    def test_a_migrated_database_has_the_list_in_order(self):
        self.assertEqual(len(NAMES), 24)
        self.assertEqual(
            list(BillCategory.objects.values_list("name", flat=True)), NAMES
        )

    def test_a_rename_keeps_the_row_and_its_vendors(self):
        BillCategory.objects.all().delete()
        phone = BillCategory.objects.create(
            name="Phone", color="#000", display_order=5
        )
        vendor = Vendor.objects.create(
            user=UserFactory(), name="AT&T", category=phone
        )

        migration.apply_list(django_apps, None)

        vendor.refresh_from_db()
        self.assertEqual(vendor.category_id, phone.id)
        self.assertEqual(vendor.category.name, "Phone & Telecom")
        self.assertEqual(vendor.category.display_order, 13)

    def test_a_category_outside_the_list_is_kept_after_it(self):
        BillCategory.objects.all().delete()
        custom = BillCategory.objects.create(
            name="Custom", color="#000", display_order=1
        )

        migration.apply_list(django_apps, None)

        custom.refresh_from_db()
        self.assertEqual(custom.display_order, 25)
        self.assertTrue(custom.is_active)
