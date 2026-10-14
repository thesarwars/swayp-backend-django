"""Web B2: payment methods of a vendor you can't see is a 404, as the
vendor itself is."""

import uuid

from django.test import TestCase
from rest_framework.test import APIClient

from apps.vendors.factories import UserFactory, VendorFactory


class UnknownVendorTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def url(self, vendor_id):
        return f"/api/v1/vendors/{vendor_id}/payment-methods"

    def test_unknown_or_foreign_vendor_is_404(self):
        for vendor_id in (uuid.uuid4(), VendorFactory().id):
            with self.subTest(vendor_id=vendor_id):
                response = self.client.get(self.url(vendor_id))

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["message"], "Vendor not found.")

    def test_own_vendor_lists(self):
        vendor = VendorFactory(user=self.user)

        self.assertEqual(self.client.get(self.url(vendor.id)).status_code, 200)
