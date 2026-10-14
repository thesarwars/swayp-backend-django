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
        "method_type": "ACH", "provider": "STRIPE",
        "provider_token": "btok_8837", "account_last4": "8837",
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
        self.assertTrue(response.data["data"]["payment_methods"][0]["is_primary"])

    def test_the_first_method_is_primary(self):
        response = self.create_vendor("First", self.ACH)

        self.assertTrue(response.data["data"]["payment_methods"][0]["is_primary"])

    def test_missing_branch_fields_are_rejected(self):
        response = self.create_vendor(
            "Broken", {"method_type": "ACH", "provider": "STRIPE"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("payment_method", response.data["errors"])

    def test_server_controlled_flags_cannot_be_claimed(self):
        response = self.create_vendor(
            "Liar", {**self.NETWORK, "payee_verified": True,
                     "supports_same_day": True}
        )

        method = response.data["data"]["payment_methods"][0]
        self.assertFalse(method["payee_verified"])
        self.assertFalse(method["supports_same_day"])


class SoftDeleteTests(VendorTestCase):

    def test_delete_is_soft_and_hides_the_vendor(self):
        vendor_id = self.create_vendor("Gone", self.ACH).data["data"]["id"]

        self.assertEqual(
            self.client.delete(f"/api/v1/vendors/{vendor_id}").status_code,
            204,
        )
        self.assertEqual(
            Vendor.objects.get(id=vendor_id).status, VendorStatus.DELETED
        )
        self.assertEqual(
            self.client.get("/api/v1/vendors").data["data"], []
        )

    def test_a_deleted_vendor_is_visible_under_the_status_filter(self):
        vendor_id = self.create_vendor("Gone", self.ACH).data["data"]["id"]
        self.client.delete(f"/api/v1/vendors/{vendor_id}")

        response = self.client.get("/api/v1/vendors?status=DELETED")

        self.assertEqual(len(response.data["data"]), 1)


class PrimaryPromotionTests(VendorTestCase):

    def setUp(self):
        super().setUp()
        self.vendor_id = self.create_vendor("WeWork", self.ACH).data["data"]["id"]
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

        row = self.client.get("/api/v1/vendors").data["data"][0]
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
        vendor_id = self.create_vendor("Checky", self.CHECK).data["data"]["id"]
        vendor = Vendor.objects.get(id=vendor_id)
        method = vendor.payment_methods.first()

        Bill.objects.create(
            user=self.user, vendor=vendor, category=self.category,
            payment_method=method, amount=Decimal("1500.00"),
            frequency=BillFrequency.MONTHLY, anchor_date=D(2026, 3, 1),
        )

        summary = self.client.get("/api/v1/vendors/summary").data["data"]

        self.assertEqual(str(summary["check_total"]), "1500.00")

    def test_check_total_ignores_deleted_bills(self):
        vendor_id = self.create_vendor("Checky", self.CHECK).data["data"]["id"]
        vendor = Vendor.objects.get(id=vendor_id)
        method = vendor.payment_methods.first()

        from django.utils import timezone

        Bill.objects.create(
            user=self.user, vendor=vendor, category=self.category,
            payment_method=method, amount=Decimal("1500.00"),
            frequency=BillFrequency.MONTHLY, anchor_date=D(2026, 3, 1),
            deleted_at=timezone.now(),
        )

        summary = self.client.get("/api/v1/vendors/summary").data["data"]

        self.assertEqual(Decimal(summary["check_total"]), Decimal("0"))

    def test_vendor_detail_exposes_the_spend_panel(self):
        vendor_id = self.create_vendor("Detail", self.ACH).data["data"]["id"]

        data = self.client.get(f"/api/v1/vendors/{vendor_id}").data["data"]

        self.assertIn("total_paid", data)
        self.assertIn("monthly_spend", data)
        self.assertIn("next_bill", data)
        self.assertEqual(len(data["monthly_spend"]), 12)


class DeleteStopsBillsTests(TestCase):
    """VEND-11: deleting a vendor stops its bills — no new occurrences, no
    autopay — and restore brings them back on REMIND."""

    def setUp(self):
        from apps.bills.factories import BillFactory, BillOccurrenceFactory
        from apps.bills.models.standing_authorization import (
            StandingAuthorization,
        )
        from apps.common.enums import AutopayMode
        from apps.vendors.factories import UserFactory, VendorFactory

        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.vendor = VendorFactory(user=self.user)
        self.bill = BillFactory(
            user=self.user, vendor=self.vendor,
            autopay_mode=AutopayMode.AUTO,
            anchor_date=dt.date(2030, 1, 1),
        )
        self.upcoming = BillOccurrenceFactory(
            bill=self.bill, due_date=dt.date(2030, 1, 1)
        )
        StandingAuthorization.objects.create(
            bill=self.bill, authorization_text="I authorize…",
            accepted_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
            ip="203.0.113.9",
        )
        self.StandingAuthorization = StandingAuthorization

    def delete(self):
        return self.client.delete(f"/api/v1/vendors/{self.vendor.id}")

    def test_delete_takes_the_bills_down_with_it(self):
        from apps.bills.models.bill_occurrence import BillOccurrence

        self.assertEqual(self.delete().status_code, 204)

        self.bill.refresh_from_db()
        self.assertIsNotNone(self.bill.deleted_at)
        self.assertFalse(
            BillOccurrence.objects.filter(pk=self.upcoming.pk).exists()
        )
        self.assertIsNotNone(
            self.StandingAuthorization.objects.get().revoked_at
        )

    def test_autopay_no_longer_finds_the_bill(self):
        from apps.payments.services.autopay_service import AutopayService

        self.delete()

        due = AutopayService().due_occurrences(today=dt.date(2030, 1, 1))

        self.assertFalse(any(o.bill_id == self.bill.id for o in due))

    def test_restore_brings_the_bills_back_on_remind(self):
        from apps.common.enums import AutopayMode

        self.delete()

        response = self.client.post(f"/api/v1/vendors/{self.vendor.id}/restore")

        self.assertEqual(response.status_code, 200)
        self.vendor.refresh_from_db()
        self.bill.refresh_from_db()
        self.assertEqual(self.vendor.status, VendorStatus.ACTIVE)
        self.assertIsNone(self.bill.deleted_at)
        self.assertEqual(self.bill.autopay_mode, AutopayMode.REMIND)
        self.assertTrue(self.bill.occurrences.exists())

    def test_a_bill_deleted_earlier_stays_deleted(self):
        from apps.bills.factories import BillFactory
        from django.utils import timezone

        earlier = BillFactory(
            user=self.user, vendor=self.vendor,
            deleted_at=timezone.now() - dt.timedelta(days=3),
        )

        self.delete()
        self.client.post(f"/api/v1/vendors/{self.vendor.id}/restore")

        earlier.refresh_from_db()
        self.assertIsNotNone(earlier.deleted_at)

    def test_restoring_an_active_vendor_is_a_400(self):
        response = self.client.post(f"/api/v1/vendors/{self.vendor.id}/restore")

        self.assertEqual(response.status_code, 400)


class PaymentMethodShapeTests(TestCase):
    """VEND-2 / VEND-3: method writes answer with the read shape, never the
    token, and a vendor's first method becomes primary."""

    def setUp(self):
        from apps.vendors.factories import UserFactory, VendorFactory

        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.vendor = VendorFactory(user=self.user)
        self.url = f"/api/v1/vendors/{self.vendor.id}/payment-methods"
        self.ach = {
            "method_type": "ACH", "provider": "STRIPE",
            "provider_token": "pm_1Nstripeabc", "account_last4": "4821",
            "account_holder_name": "Acme LLC",
        }

    def test_the_first_method_becomes_primary(self):
        response = self.client.post(self.url, self.ach, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["data"]["is_primary"])
        self.assertEqual(response.data["data"]["account_ref"], "****4821")
        self.assertIn("id", response.data["data"])
        self.assertNotIn("provider_token", response.data["data"])

    def test_a_second_method_does_not_steal_primary(self):
        self.client.post(self.url, self.ach, format="json")
        second = self.client.post(
            self.url, {**self.ach, "account_last4": "9999"}, format="json"
        )

        self.assertFalse(second.data["data"]["is_primary"])

    def test_patch_never_echoes_the_token(self):
        method_id = self.client.post(self.url, self.ach, format="json").data["data"]["id"]

        response = self.client.patch(
            f"{self.url}/{method_id}",
            {"account_holder_name": "Acme Inc"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("provider_token", response.data["data"])
        self.assertEqual(response.data["data"]["account_holder_name"], "Acme Inc")
        self.assertEqual(response.data["data"]["account_ref"], "****4821")


class VendorBodiesTests(TestCase):
    """VEND-9: PATCH returns the vendor; money is a 2dp string."""

    def setUp(self):
        from apps.vendors.factories import (
            UserFactory,
            VendorFactory,
            VendorPaymentMethodFactory,
        )

        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.vendor = VendorFactory(user=self.user)
        VendorPaymentMethodFactory(vendor=self.vendor)

    def test_patch_returns_the_full_vendor(self):
        response = self.client.patch(
            f"/api/v1/vendors/{self.vendor.id}", {"notes": "net 30"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["notes"], "net 30")
        for key in ("id", "payment_methods", "total_paid", "bills"):
            self.assertIn(key, response.data["data"])

    def test_money_is_a_string_even_when_zero(self):
        data = self.client.get(f"/api/v1/vendors/{self.vendor.id}").json()["data"]

        self.assertEqual(data["total_paid"], "0.00")
        self.assertEqual(data["monthly_spend"][0]["total"], "0.00")

    def test_methods_carry_account_type_and_network_ref(self):
        method = self.client.get(f"/api/v1/vendors/{self.vendor.id}").json()[
            "data"
        ]["payment_methods"][0]

        self.assertIn("account_type", method)
        self.assertIn("network_payee_ref", method)
        self.assertNotIn("provider_token", method)


class ContactFieldsTests(TestCase):
    """VEND-4: contact person, phone and email are stored and returned."""

    def test_patch_and_read_the_contact(self):
        from apps.vendors.factories import UserFactory, VendorFactory

        user = UserFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        vendor = VendorFactory(user=user)

        response = client.patch(
            f"/api/v1/vendors/{vendor.id}",
            {"contact_name": "Dana Lee", "contact_phone": "+14155550101",
             "contact_email": "ap@wework.example"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["contact_name"], "Dana Lee")
        detail = client.get(f"/api/v1/vendors/{vendor.id}").data["data"]
        self.assertEqual(detail["contact_email"], "ap@wework.example")

    def test_a_bad_email_is_refused(self):
        from apps.vendors.factories import UserFactory, VendorFactory

        user = UserFactory()
        client = APIClient()
        client.force_authenticate(user=user)
        vendor = VendorFactory(user=user)

        response = client.patch(
            f"/api/v1/vendors/{vendor.id}", {"contact_email": "nope"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)


class ListRowAndCategoryTests(TestCase):
    """VEND-8 / VEND-7: list rows say status and category; category is
    optional on create."""

    def setUp(self):
        from apps.vendors.factories import UserFactory

        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.other = BillCategory.objects.get_or_create(
            name="Other",
            defaults={"icon": "https://e.com/o.png", "color": "#999"},
        )[0]

    def create(self, **extra):
        body = {
            "name": "Acme", "source": "MANUAL",
            "payment_method": {
                "method_type": "CHECK", "check_legal_name": "Acme Inc",
                "street": "1 Main St", "city": "Austin", "state": "TX",
                "zip_code": "78701",
            },
        }
        body.update(extra)
        return self.client.post("/api/v1/vendors", body, format="json")

    def test_without_a_category_the_vendor_is_filed_under_other(self):
        response = self.create()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(str(response.data["data"]["category"]), str(self.other.id))

    def test_list_rows_carry_status_and_category(self):
        self.create()

        row = self.client.get("/api/v1/vendors").data["data"][0]

        self.assertEqual(row["status"], "ACTIVE")
        self.assertEqual(row["category_name"], "Other")
        self.assertIn("created_at", row)
        self.assertIn("updated_at", row)


class DirectoryContractTests(TestCase):
    """VEND-6: a directory hit maps onto a NETWORK vendor without guesswork."""

    def setUp(self):
        from apps.vendors.factories import UserFactory

        self.client = APIClient()
        self.client.force_authenticate(user=UserFactory())

    def test_a_hit_becomes_a_network_vendor(self):
        hits = self.client.get("/api/v1/vendors/directory-search?q=verizon").json()["data"]
        hits = hits.get("items", hits) if isinstance(hits, dict) else hits
        self.assertTrue(hits, "the mock directory returned nothing")
        hit = hits[0]
        self.assertIn("category_id", hit)

        if hit["category_id"] is None:
            BillCategory.objects.create(
                name=hit["category"], icon="https://e.com/c.png", color="#123"
            )
            hit = self.client.get("/api/v1/vendors/directory-search?q=verizon").json()["data"]
            hit = hit[0]

        response = self.client.post(
            "/api/v1/vendors",
            {
                "name": hit["name"],
                "category": hit["category_id"],
                "source": "DIRECTORY",
                "payment_method": {
                    "method_type": "NETWORK",
                    "network_payee_ref": hit["external_id"],
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        vendor = Vendor.objects.get(id=response.data["data"]["id"])
        self.assertEqual(vendor.directory_payee_id, hit["external_id"])
        self.assertEqual(
            response.data["data"]["payment_methods"][0]["network_payee_ref"],
            hit["external_id"],
        )


class VendorActivityFeedTests(TestCase):
    """VEND-5: the recent-activities screen has a real feed."""

    def setUp(self):
        from apps.vendors.factories import UserFactory

        self.user = UserFactory(first_name="Ada", last_name="Reed")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.category = BillCategory.objects.get_or_create(
            name="Rent",
            defaults={"icon": "https://e.com/r.png", "color": "#111"},
        )[0]

    def feed(self):
        return self.client.get("/api/v1/vendors/activity").json()["data"]

    def test_add_edit_delete_restore_are_recorded_newest_first(self):
        vendor_id = self.client.post(
            "/api/v1/vendors",
            {
                "name": "WeWork", "category": str(self.category.id),
                "source": "MANUAL",
                "payment_method": {
                    "method_type": "CHECK", "check_legal_name": "WeWork Inc",
                    "street": "1 Main", "city": "Austin", "state": "TX",
                    "zip_code": "78701",
                },
            },
            format="json",
        ).data["data"]["id"]
        self.client.patch(
            f"/api/v1/vendors/{vendor_id}", {"notes": "x"}, format="json"
        )
        self.client.delete(f"/api/v1/vendors/{vendor_id}")
        self.client.post(f"/api/v1/vendors/{vendor_id}/restore")

        rows = self.feed()

        self.assertEqual(
            [r["action"] for r in rows],
            ["RESTORED", "DELETED", "UPDATED", "CREATED"],
        )
        self.assertEqual(rows[-1]["vendor_name"], "WeWork")
        self.assertEqual(rows[-1]["actor_name"], "Ada Reed")
        self.assertEqual(rows[-1]["label"], "Vendor added")

    def test_another_accounts_activity_is_not_shown(self):
        from apps.vendors.factories import UserFactory, VendorFactory
        from apps.vendors.models import VendorActivityAction, record_vendor_activity

        theirs = VendorFactory(user=UserFactory())
        record_vendor_activity(vendor=theirs, action=VendorActivityAction.CREATED)

        self.assertEqual(self.feed(), [])
