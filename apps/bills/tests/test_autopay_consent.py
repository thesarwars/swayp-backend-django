"""Autopay standing authorization + review echo (E4-S3 / E4-S5)."""

import datetime as dt

from django.test import TestCase
from django.test.utils import setup_test_environment
from rest_framework.test import APIClient

from apps.bill_categories.models import BillCategory
from apps.bills.models.standing_authorization import StandingAuthorization
from apps.common.enums import AutopayMode
from apps.users.models import User
from apps.vendors.models import Vendor

D = dt.date

AUTHORIZATION_TEXT = (
    "I authorize Swayp to debit my account for this recurring bill until I "
    "revoke this authorization."
)


class AutopayConsentTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="consent@example.com",
            password="Sw@yp-Test-1",
        )
        self.category = BillCategory.objects.create(
            name="Commercial Rent", icon="https://e.com/i.png", color="#111",
        )
        self.vendor = Vendor.objects.create(
            user=self.user, name="WeWork", category=self.category,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def payload(self, **overrides):
        body = {
            "vendor": str(self.vendor.id),
            "category": str(self.category.id),
            "bill_type": "FIXED",
            "amount": "3200.00",
            "frequency": "MONTHLY",
            "anchor_date": "2027-01-01",
            "autopay_mode": "REMIND",
            "source": "MANUAL",
        }
        body.update(overrides)
        return body

    def consent(self, accepted=True):
        return {
            "accepted": accepted,
            "authorization_text": AUTHORIZATION_TEXT,
        }

    def create(self, **overrides):
        return self.client.post(
            "/api/v1/bills/create", self.payload(**overrides), format="json"
        )


class ConsentRequiredTests(AutopayConsentTestCase):

    def test_auto_without_consent_is_rejected(self):
        response = self.create(autopay_mode="AUTO")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(StandingAuthorization.objects.count(), 0)

    def test_auto_with_consent_not_accepted_is_rejected(self):
        response = self.create(
            autopay_mode="AUTO", autopay_consent=self.consent(accepted=False)
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(StandingAuthorization.objects.count(), 0)

    def test_auto_with_blank_authorization_text_is_rejected(self):
        response = self.create(
            autopay_mode="AUTO",
            autopay_consent={"accepted": True, "authorization_text": "   "},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(StandingAuthorization.objects.count(), 0)

    def test_rejected_auto_creates_no_bill_at_all(self):
        """The create is atomic — no orphan bill set to AUTO."""
        from apps.bills.models.bill import Bill

        self.create(autopay_mode="AUTO")

        self.assertEqual(Bill.objects.count(), 0)

    def test_remind_creates_no_authorization(self):
        response = self.create(autopay_mode="REMIND")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(StandingAuthorization.objects.count(), 0)

    def test_remind_with_consent_is_rejected(self):
        response = self.create(
            autopay_mode="REMIND", autopay_consent=self.consent()
        )

        self.assertEqual(response.status_code, 400)


class ConsentCaptureTests(AutopayConsentTestCase):

    def test_auto_with_consent_records_the_authorization(self):
        response = self.create(
            autopay_mode="AUTO", autopay_consent=self.consent()
        )

        self.assertEqual(response.status_code, 201)

        authorization = StandingAuthorization.objects.get()
        self.assertEqual(
            authorization.authorization_text, AUTHORIZATION_TEXT
        )
        self.assertIsNotNone(authorization.accepted_at)
        self.assertIsNone(authorization.revoked_at)

    def test_authorization_records_the_client_ip(self):
        self.create(autopay_mode="AUTO", autopay_consent=self.consent())

        self.assertEqual(StandingAuthorization.objects.get().ip, "127.0.0.1")

    def test_forwarded_ip_wins_over_the_proxy_address(self):
        self.client.post(
            "/api/v1/bills/create",
            self.payload(
                autopay_mode="AUTO", autopay_consent=self.consent()
            ),
            format="json",
            HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1",
        )

        self.assertEqual(StandingAuthorization.objects.get().ip, "203.0.113.9")

    def test_authorization_records_the_user_agent(self):
        self.client.post(
            "/api/v1/bills/create",
            self.payload(
                autopay_mode="AUTO", autopay_consent=self.consent()
            ),
            format="json",
            HTTP_USER_AGENT="SwaypApp/1.2 (iOS 18)",
        )

        self.assertEqual(
            StandingAuthorization.objects.get().user_agent,
            "SwaypApp/1.2 (iOS 18)",
        )


class ConsentToggleTests(AutopayConsentTestCase):

    def enable_autopay(self):
        response = self.create(
            autopay_mode="AUTO", autopay_consent=self.consent()
        )
        return response.data["data"]["id"]

    def test_turning_autopay_off_revokes_the_authorization(self):
        bill_id = self.enable_autopay()

        response = self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"autopay_mode": "REMIND"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            StandingAuthorization.objects.get().revoked_at
        )

    def test_turning_autopay_back_on_captures_a_fresh_authorization(self):
        bill_id = self.enable_autopay()

        self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"autopay_mode": "REMIND"},
            format="json",
        )
        self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"autopay_mode": "AUTO", "autopay_consent": self.consent()},
            format="json",
        )

        # Both consent events survive; only the newest is live.
        self.assertEqual(StandingAuthorization.objects.count(), 2)
        self.assertEqual(
            StandingAuthorization.objects.filter(
                revoked_at__isnull=True
            ).count(),
            1,
        )

    def test_switching_to_auto_without_consent_is_rejected(self):
        response = self.create(autopay_mode="REMIND")
        bill_id = response.data["data"]["id"]

        response = self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"autopay_mode": "AUTO"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(StandingAuthorization.objects.count(), 0)

    def test_editing_other_fields_leaves_the_authorization_alone(self):
        bill_id = self.enable_autopay()

        self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"notes": "renewed"},
            format="json",
        )

        self.assertEqual(StandingAuthorization.objects.count(), 1)
        self.assertIsNone(StandingAuthorization.objects.get().revoked_at)

    def test_deleting_the_bill_revokes_the_authorization(self):
        bill_id = self.enable_autopay()

        self.client.delete(f"/api/v1/bills/{bill_id}/details")

        self.assertIsNotNone(
            StandingAuthorization.objects.get().revoked_at,
            msg="a debit mandate must not outlive the bill",
        )


class ReviewEchoTests(AutopayConsentTestCase):

    def test_auto_review_states_swayp_will_pay(self):
        response = self.create(
            autopay_mode="AUTO", autopay_consent=self.consent()
        )
        data = response.data["data"]

        self.assertEqual(
            data["summary"],
            "Swayp will pay WeWork $3,200.00 on January 1, 2027.",
        )
        self.assertTrue(data["autopay_authorized"])

    def test_remind_review_states_a_reminder(self):
        response = self.create(autopay_mode="REMIND")
        data = response.data["data"]

        self.assertEqual(
            data["summary"],
            "We'll remind you to pay WeWork $3,200.00 on January 1, 2027.",
        )
        self.assertFalse(data["autopay_authorized"])

    def test_review_carries_the_structured_parts(self):
        response = self.create(autopay_mode="REMIND")
        data = response.data["data"]

        self.assertEqual(data["vendor"], "WeWork")
        self.assertEqual(data["category"], "Commercial Rent")
        self.assertEqual(data["frequency"], "MONTHLY")
        self.assertEqual(str(data["next_due_date"]), "2027-01-01")

    def test_update_echoes_a_refreshed_review(self):
        response = self.create(autopay_mode="REMIND")
        bill_id = response.data["data"]["id"]

        response = self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"amount": "4100.00"},
            format="json",
        )

        self.assertIn("$4,100.00", response.data["data"]["summary"])


class ChangedTermsNeedFreshConsentTests(AutopayConsentTestCase):
    """BILLS-4: an autopay authorization covers the terms the user agreed
    to. Changing them is a different debit and needs consent again."""

    enable_autopay = ConsentToggleTests.enable_autopay

    def patch(self, bill_id, body):
        return self.client.patch(
            f"/api/v1/bills/{bill_id}/update", body, format="json"
        )

    def test_changing_the_amount_without_consent_is_rejected(self):
        bill_id = self.enable_autopay()

        response = self.patch(bill_id, {"amount": "9999.00"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("autopay_consent", response.data["errors"])

    def test_a_rejected_edit_changes_nothing(self):
        from apps.bills.models.bill import Bill

        bill_id = self.enable_autopay()

        self.patch(bill_id, {"amount": "9999.00"})

        self.assertEqual(str(Bill.objects.get(id=bill_id).amount), "3200.00")
        self.assertIsNone(StandingAuthorization.objects.get().revoked_at)

    def test_each_authorized_term_needs_consent(self):
        bill_id = self.enable_autopay()

        for body in (
            {"frequency": "QUARTERLY"},
            {"anchor_date": "2027-02-15"},
            {"bill_type": "VARIABLE"},
        ):
            with self.subTest(body=body):
                self.assertEqual(self.patch(bill_id, body).status_code, 400)

    def test_consent_with_the_change_replaces_the_authorization(self):
        bill_id = self.enable_autopay()

        response = self.patch(
            bill_id,
            {
                "amount": "4100.00",
                "autopay_consent": {
                    "accepted": True,
                    "authorization_text": "I authorize $4,100.00 monthly.",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandingAuthorization.objects.count(), 2)
        live = StandingAuthorization.objects.get(revoked_at__isnull=True)
        self.assertEqual(
            live.authorization_text, "I authorize $4,100.00 monthly."
        )

    def test_the_same_value_is_not_a_change(self):
        bill_id = self.enable_autopay()

        response = self.patch(bill_id, {"amount": "3200.00"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(StandingAuthorization.objects.count(), 1)

    def test_a_remind_bill_changes_terms_freely(self):
        bill_id = self.create(autopay_mode="REMIND").data["data"]["id"]

        self.assertEqual(self.patch(bill_id, {"amount": "1.00"}).status_code, 200)

    def test_consent_on_a_remind_bill_is_rejected(self):
        bill_id = self.create(autopay_mode="REMIND").data["data"]["id"]

        response = self.patch(
            bill_id, {"amount": "1.00", "autopay_consent": self.consent()}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(StandingAuthorization.objects.count(), 0)


class AuthorizationTextPreviewTests(AutopayConsentTestCase):
    """BILLS-3: the server writes the autopay authorization text."""

    URL = "/api/v1/bills/autopay-authorization/preview"

    def preview(self, **overrides):
        body = {
            "vendor": str(self.vendor.id),
            "amount": "3200.00",
            "frequency": "MONTHLY",
            "anchor_date": "2027-01-01",
        }
        body.update(overrides)
        return self.client.post(self.URL, body, format="json")

    def test_the_text_states_the_terms(self):
        response = self.preview()

        self.assertEqual(response.status_code, 200)
        text = response.data["data"]["authorization_text"]
        for part in ("WeWork", "$3,200.00", "every month", "January 1, 2027"):
            self.assertIn(part, text)
        self.assertIn("turn off autopay", text)

    def test_a_variable_bill_authorizes_each_bills_amount(self):
        text = self.preview(bill_type="VARIABLE").data["data"][
            "authorization_text"
        ]

        self.assertIn("the amount due on each bill", text)

    def test_no_bank_yet_names_the_account_generically(self):
        data = self.preview().data["data"]

        self.assertIsNone(data["funding_account"])
        self.assertIn("my connected bank account", data["authorization_text"])

    def test_the_linked_funding_account_is_named(self):
        from apps.banking.factories import (
            BankAccountFactory,
            BankConnectionFactory,
        )

        BankAccountFactory(
            connection=BankConnectionFactory(user=self.user), mask="4821"
        )

        data = self.preview().data["data"]

        self.assertIn("4821", data["funding_account"])
        self.assertIn("4821", data["authorization_text"])

    def test_the_preview_creates_nothing(self):
        from apps.bills.models.bill import Bill

        self.preview()

        self.assertEqual(Bill.objects.count(), 0)
        self.assertEqual(StandingAuthorization.objects.count(), 0)

    def test_the_previewed_text_is_what_gets_stored(self):
        text = self.preview().data["data"]["authorization_text"]

        self.create(
            autopay_mode="AUTO",
            autopay_consent={"accepted": True, "authorization_text": text},
        )

        self.assertEqual(
            StandingAuthorization.objects.get().authorization_text, text
        )

    def test_another_accounts_vendor_is_refused(self):
        stranger = User.objects.create_user(
            email="other@example.com", password="Sw@yp-Test-1"
        )
        theirs = Vendor.objects.create(
            user=stranger, name="Theirs", category=self.category
        )

        self.assertEqual(
            self.preview(vendor=str(theirs.id)).status_code, 400
        )


class PaymentRefTests(AutopayConsentTestCase):
    """BILLS-10: the scanned reference has its own field, not notes."""

    def test_create_stores_it_and_detail_returns_it(self):
        bill_id = self.create(payment_ref="WW-88", source="QR").data["data"]["id"]

        detail = self.client.get(f"/api/v1/bills/{bill_id}/details").data["data"]

        self.assertEqual(detail["payment_ref"], "WW-88")
        self.assertEqual(detail["notes"], "")

    def test_update_changes_it(self):
        bill_id = self.create().data["data"]["id"]

        self.client.patch(
            f"/api/v1/bills/{bill_id}/update", {"payment_ref": "ACC-1"},
            format="json",
        )

        detail = self.client.get(f"/api/v1/bills/{bill_id}/details").data["data"]
        self.assertEqual(detail["payment_ref"], "ACC-1")

    def test_it_is_capped(self):
        response = self.create(payment_ref="x" * 101)

        self.assertEqual(response.status_code, 400)


class CreateRulesTests(AutopayConsentTestCase):
    """BILLS-11: what bill create refuses, as field errors."""

    def test_an_inactive_category_is_refused(self):
        self.category.is_active = False
        self.category.save(update_fields=["is_active"])

        response = self.create()

        self.assertEqual(response.status_code, 400)
        self.assertIn("category", response.data["errors"])

    def test_a_deleted_vendor_is_refused(self):
        self.vendor.status = "DELETED"
        self.vendor.save(update_fields=["status"])

        response = self.create()

        self.assertEqual(response.status_code, 400)
        self.assertIn("vendor", response.data["errors"])

    def test_another_vendors_payment_method_is_refused(self):
        import uuid

        response = self.create(payment_method=str(uuid.uuid4()))

        self.assertEqual(response.status_code, 400)
        self.assertIn("payment_method", response.data["errors"])

    def test_notes_are_capped(self):
        self.assertEqual(self.create(notes="x" * 2001).status_code, 400)
        self.assertEqual(self.create(notes="x" * 2000).status_code, 201)

    def test_updating_to_an_inactive_category_is_refused(self):
        bill_id = self.create().data["data"]["id"]
        retired = BillCategory.objects.create(
            name="Retired", icon="https://e.com/r.png", color="#333",
            is_active=False,
        )

        response = self.client.patch(
            f"/api/v1/bills/{bill_id}/update",
            {"category": str(retired.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
