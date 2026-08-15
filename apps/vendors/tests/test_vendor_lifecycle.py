"""Vendor create branches, soft delete, primary promotion, spend (E3)."""

import datetime as dt
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.bill_categories.models import BillCategory
from apps.bills.models.bill import Bill
from apps.common.enums import BillFrequency, VendorStatus
from apps.users.models import User
from apps.vendors.models import Vendor, VendorPaymentMethod
from apps.vendors.selectors.vendor_selector import VendorSelector

D = dt.date


class VendorTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="vendor@example.com", password="Sw@yp-Test-1"
        )
        self.category = BillCategory.objects.create(
            name="Commercial Rent", icon="https://e.com/i.png", color="#111"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def create_vendor(self, name, method):
        return self.client.post(
            "/api/v1/vendors",
            {
                "name": name,
                "category": str(self.category.id),
                "source": "MANUAL",
                "payment_method": method,
            },
            format="json",
        )

    ACH = {
        "method_type": "ACH", "provider": "MOOV",
        "provider_token": "tok", "account_last4": "8837",
        "account_holder_name": "WeWork Inc",
    }
    CHECK = {
        "method_type": "CHECK", "check_legal_name": "WeWork Inc",
        "street": "115 W 18th St", "city": "New York", "state": "NY",
        "zip_code": "10011",
    }
    NETWORK = {"method_type": "NETWORK", "network_payee_ref": "payee_1"}


class CreateBranchTests(VendorTestCase):

    def test_all_three_branches_create(self):
        for label, method in [
            ("NETWORK", self.NETWORK),
            ("ACH", self.ACH),
            ("CHECK", self.CHECK),
        ]:
            with self.subTest(branch=label):
                response = self.create_vendor(f"V-{label}", method)
                self.assertEqual(response.status_code, 201)

    def test_is_primary_in_the_payload_does_not_crash(self):
        """Regression: passing is_primary collided with the service kwarg."""
        response = self.create_vendor("Explicit", {**self.ACH, "is_primary": True})

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["payment_methods"][0]["is_primary"])

    def test_the_first_method_is_primary(self):
        response = self.create_vendor("First", self.ACH)

        self.assertTrue(response.data["payment_methods"][0]["is_primary"])

    def test_missing_branch_fields_are_rejected(self):
        response = self.create_vendor(
            "Broken", {"method_type": "ACH", "provider": "MOOV"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("payment_method", response.data["errors"])

    def test_server_controlled_flags_cannot_be_claimed(self):
        response = self.create_vendor(
            "Liar", {**self.NETWORK, "payee_verified": True,
                     "supports_same_day": True}
        )

        method = response.data["payment_methods"][0]
        self.assertFalse(method["payee_verified"])
        self.assertFalse(method["supports_same_day"])


class SoftDeleteTests(VendorTestCase):

    def test_delete_is_soft_and_hides_the_vendor(self):
        vendor_id = self.create_vendor("Gone", self.ACH).data["id"]

        self.assertEqual(
            self.client.delete(f"/api/v1/vendors/{vendor_id}").status_code,
            204,
        )
        self.assertEqual(
            Vendor.objects.get(id=vendor_id).status, VendorStatus.DELETED
        )
        self.assertEqual(
            self.client.get("/api/v1/vendors").data["items"], []
        )

    def test_a_deleted_vendor_is_visible_under_the_status_filter(self):
        vendor_id = self.create_vendor("Gone", self.ACH).data["id"]
        self.client.delete(f"/api/v1/vendors/{vendor_id}")

        response = self.client.get("/api/v1/vendors?status=DELETED")

        self.assertEqual(len(response.data["items"]), 1)


class PrimaryPromotionTests(VendorTestCase):

    def setUp(self):
        super().setUp()
        self.vendor_id = self.create_vendor("WeWork", self.ACH).data["id"]
        self.client.post(
            f"/api/v1/vendors/{self.vendor_id}/payment-methods",
            self.CHECK, format="json",
        )

    def primary_count(self):
        return VendorPaymentMethod.objects.filter(
            vendor_id=self.vendor_id, is_primary=True
        ).count()

    def test_deleting_the_primary_promotes_a_replacement(self):
        primary = VendorPaymentMethod.objects.get(
            vendor_id=self.vendor_id, is_primary=True
        )

        self.client.delete(
            f"/api/v1/vendors/{self.vendor_id}/payment-methods/{primary.id}"
        )

        self.assertEqual(self.primary_count(), 1)

    def test_the_rail_chip_survives_deleting_the_primary(self):
        primary = VendorPaymentMethod.objects.get(
            vendor_id=self.vendor_id, is_primary=True
        )

        self.client.delete(
            f"/api/v1/vendors/{self.vendor_id}/payment-methods/{primary.id}"
        )

        row = self.client.get("/api/v1/vendors").data["items"][0]
        self.assertEqual(row["payment_rail"], "CHECK")

    def test_deleting_a_non_primary_changes_nothing(self):
        secondary = VendorPaymentMethod.objects.get(
            vendor_id=self.vendor_id, is_primary=False
        )

        self.client.delete(
            f"/api/v1/vendors/{self.vendor_id}/payment-methods/{secondary.id}"
        )

        self.assertEqual(self.primary_count(), 1)

    def test_deleting_the_last_method_leaves_none(self):
        for method in VendorPaymentMethod.objects.filter(
            vendor_id=self.vendor_id
        ):
            self.client.delete(
                f"/api/v1/vendors/{self.vendor_id}"
                f"/payment-methods/{method.id}"
            )

        self.assertEqual(self.primary_count(), 0)


class SpendTests(VendorTestCase):

    def test_monthly_spend_is_a_dense_twelve_bucket_series(self):
        vendor = Vendor.objects.create(
            user=self.user, name="Quiet", category=self.category
        )

        series = VendorSelector.monthly_spend(vendor, today=D(2026, 7, 15))

        self.assertEqual(len(series), 12)
        self.assertEqual(series[-1]["month"], "2026-07")
        self.assertEqual(series[0]["month"], "2025-08")
        self.assertTrue(all(bucket["total"] == 0 for bucket in series))

    def test_check_total_sums_bills_routed_over_check(self):
        vendor_id = self.create_vendor("Checky", self.CHECK).data["id"]
        vendor = Vendor.objects.get(id=vendor_id)
        method = vendor.payment_methods.first()

        Bill.objects.create(
            user=self.user, vendor=vendor, category=self.category,
            payment_method=method, amount=Decimal("1500.00"),
            frequency=BillFrequency.MONTHLY, anchor_date=D(2026, 3, 1),
        )

        summary = self.client.get("/api/v1/vendors/summary").data

        self.assertEqual(str(summary["check_total"]), "1500.00")

    def test_check_total_ignores_deleted_bills(self):
        vendor_id = self.create_vendor("Checky", self.CHECK).data["id"]
        vendor = Vendor.objects.get(id=vendor_id)
        method = vendor.payment_methods.first()

        from django.utils import timezone

        Bill.objects.create(
            user=self.user, vendor=vendor, category=self.category,
            payment_method=method, amount=Decimal("1500.00"),
            frequency=BillFrequency.MONTHLY, anchor_date=D(2026, 3, 1),
            deleted_at=timezone.now(),
        )

        summary = self.client.get("/api/v1/vendors/summary").data

        self.assertEqual(Decimal(summary["check_total"]), Decimal("0"))

    def test_vendor_detail_exposes_the_spend_panel(self):
        vendor_id = self.create_vendor("Detail", self.ACH).data["id"]

        data = self.client.get(f"/api/v1/vendors/{vendor_id}").data

        self.assertIn("total_paid", data)
        self.assertIn("monthly_spend", data)
        self.assertIn("next_bill", data)
        self.assertEqual(len(data["monthly_spend"]), 12)
