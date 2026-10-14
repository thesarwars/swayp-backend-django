"""Web B10: vendor category is optional for real: omitted, "" or null all
file the vendor under Other, and PUT may leave it out."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.bill_categories.models import BillCategory
from apps.vendors.factories import UserFactory, VendorFactory

NETWORK = {"method_type": "NETWORK", "network_payee_ref": "payee_1"}


class OptionalCategoryTests(TestCase):

    def setUp(self):
        self.other = BillCategory.objects.get_or_create(
            name="Other", defaults={"color": "#999"}
        )[0]
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_omitted_empty_or_null_means_other(self):
        for i, extra in enumerate(({}, {"category": ""}, {"category": None})):
            with self.subTest(extra=extra):
                response = self.client.post("/api/v1/vendors", {
                    "name": f"Vendor {i}", "source": "MANUAL",
                    "payment_method": NETWORK, **extra,
                }, format="json")

                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual(response.json()["category"], str(self.other.id))

    def test_put_without_category_keeps_it(self):
        vendor = VendorFactory(user=self.user)
        before = vendor.category_id

        response = self.client.put(
            f"/api/v1/vendors/{vendor.id}", {"name": "Renamed"}, format="json"
        )

        self.assertEqual(response.status_code, 200, response.content)
        vendor.refresh_from_db()
        self.assertEqual(vendor.category_id, before)
