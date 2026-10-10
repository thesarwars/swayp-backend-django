"""API-1: the published schema matches what the server sends.

Each test calls a real endpoint and validates the body against the schema
published for it. Add the endpoint here when you add or change one.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.tests.openapi_contract import assert_matches_schema
from apps.vendors.factories import UserFactory


class ContractTestCase(TestCase):

    def setUp(self):
        self.user = UserFactory(is_active=True, is_verified=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def check(self, method, url, path=None, body=None, status=None):
        response = getattr(self.client, method.lower())(
            url, body, format="json"
        ) if body is not None else getattr(self.client, method.lower())(url)

        if status is not None:
            self.assertEqual(response.status_code, status, response.content)

        assert_matches_schema(self, response, method, path or url)

        return response


class ErrorContractTests(ContractTestCase):

    def test_validation_error(self):
        self.check("POST", "/api/v1/billing/subscription",
                   body={"plan": "NOPE"}, status=400)

    def test_not_found(self):
        self.check(
            "GET", "/api/v1/payments/00000000-0000-0000-0000-000000000000",
            path="/api/v1/payments/{payment_id}", status=404,
        )

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)

        self.check("GET", "/api/v1/billing/subscription", status=401)


class BillingContractTests(ContractTestCase):

    def subscribe(self):
        return self.check(
            "POST", "/api/v1/billing/subscription",
            body={"plan": "STANDARD"}, status=201,
        )

    def test_plans(self):
        self.check("GET", "/api/v1/billing/plans", status=200)

    def test_subscription_lifecycle(self):
        self.check("GET", "/api/v1/billing/subscription", status=200)
        self.subscribe()
        self.check("GET", "/api/v1/billing/subscription", status=200)
        self.check("PATCH", "/api/v1/billing/subscription",
                   body={"plan": "ENTERPRISE"}, status=200)
        self.check("DELETE", "/api/v1/billing/subscription", status=200)
        self.check("POST", "/api/v1/billing/subscription/resume", status=200)

    def test_reads(self):
        self.subscribe()

        for url in ("/api/v1/billing/allowances", "/api/v1/billing/invoice",
                    "/api/v1/billing/fees", "/api/v1/billing/invoices",
                    "/api/v1/billing/config", "/api/v1/billing/addons",
                    "/api/v1/billing/payment-method"):
            with self.subTest(url=url):
                self.check("GET", url, status=200)

    def test_addons(self):
        self.check("POST", "/api/v1/billing/subscription",
                   body={"plan": "ENTERPRISE"}, status=201)

        self.check("POST", "/api/v1/billing/addons",
                   body={"kind": "ERP_SYNC", "quantity": 1}, status=200)
        self.check("POST", "/api/v1/billing/addons",
                   body={"kind": "ERP_SYNC", "quantity": 0}, status=200)


class AuthContractTests(ContractTestCase):

    EMAIL = "contract@acme.com"
    PASSWORD = "Str0ng!Passphrase1"

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=None)

    def register(self):
        return self.check("POST", "/api/v1/auth/register", body={
            "first_name": "Jane", "last_name": "Smith", "email": self.EMAIL,
            "business_name": "Acme", "password": self.PASSWORD,
            "terms_accepted": True, "signatory_confirmed": True,
        }, status=201)

    def code(self, purpose):
        from datetime import timedelta

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from apps.authentication.models import OTP
        from apps.authentication.utils.otp import OTPService

        user = get_user_model().objects.get(email=self.EMAIL)
        OTP.objects.filter(user=user).delete()
        OTP.objects.create(
            user=user, code_hash=OTPService.hash_otp("123456"),
            purpose=purpose, expires_at=timezone.now() + timedelta(minutes=5),
        )

    def test_the_whole_flow(self):
        from apps.authentication.models import OTPPurpose

        self.register()
        self.check("POST", "/api/v1/auth/resend-otp",
                   body={"email": self.EMAIL, "purpose": "REGISTRATION"},
                   status=429)  # registration has just sent one
        self.code(OTPPurpose.REGISTRATION)
        self.check("POST", "/api/v1/auth/verify-otp",
                   body={"email": self.EMAIL, "otp": "123456"}, status=200)

        tokens = self.check("POST", "/api/v1/auth/login", body={
            "email": self.EMAIL, "password": self.PASSWORD,
        }, status=200).json()["data"]

        self.check("POST", "/api/v1/auth/refresh",
                   body={"refresh": tokens["refresh"]}, status=200)
        self.check("POST", "/api/v1/auth/forgot-password",
                   body={"email": self.EMAIL}, status=200)
        self.code(OTPPurpose.RESET_PASSWORD)
        self.check("POST", "/api/v1/auth/verify-otp", body={
            "email": self.EMAIL, "otp": "123456",
            "purpose": "RESET_PASSWORD"}, status=200)
        self.code(OTPPurpose.RESET_PASSWORD)
        self.check("POST", "/api/v1/auth/reset-password", body={
            "email": self.EMAIL, "otp": "123456",
            "password": "An0ther!Passphrase2"}, status=200)
        self.check("POST", "/api/v1/auth/login/phone/request",
                   body={"phone_number": "+14155552671"}, status=200)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        refreshed = self.check(
            "POST", "/api/v1/auth/logout",
            body={"refresh": tokens["refresh"]}, status=400,
        )  # spent above by refresh, which rotates it
        self.assertEqual(refreshed.json()["code"], "validation_failed")

    def test_bad_login(self):
        self.check("POST", "/api/v1/auth/login",
                   body={"email": "x@y.com", "password": "nope"}, status=400)


class UserContractTests(ContractTestCase):

    def setUp(self):
        super().setUp()
        from apps.users.models import Profile

        Profile.objects.get_or_create(user=self.user, defaults={
            "full_name": "Jane Smith", "account_type": "BUSINESS"})

    def test_profile_and_onboarding(self):
        self.check("GET", "/api/v1/users/profile", status=200)
        self.check("PATCH", "/api/v1/users/profile",
                   body={"full_name": "Jane Q Smith"}, status=200)
        self.check("GET", "/api/v1/users/onboarding", status=200)
        self.check("POST", "/api/v1/users/onboarding/skip-bank", status=200)


class DashboardContractTests(ContractTestCase):

    def test_home_and_summary(self):
        from apps.notifications.factories import NotificationFactory

        NotificationFactory(user=self.user)
        self.check("GET", "/api/v1/dashboard/home", status=200)
        self.check("GET", "/api/v1/dashboard/profile-summary", status=200)


class NotificationContractTests(ContractTestCase):

    def test_list_and_read(self):
        from apps.notifications.factories import NotificationFactory

        rows = NotificationFactory.create_batch(3, user=self.user)

        self.check("GET", "/api/v1/notifications?pageSize=2",
                   path="/api/v1/notifications", status=200)
        self.check(
            "PATCH", f"/api/v1/notifications/{rows[0].id}/read",
            path="/api/v1/notifications/{notification_id}/read", status=200,
        )
        self.check("PATCH", "/api/v1/notifications/read-all", status=200)

    def test_preferences_and_devices(self):
        self.check("GET", "/api/v1/notifications/preferences", status=200)
        self.check("PATCH", "/api/v1/notifications/preferences",
                   body={"preferences": [
                       {"type": "BILL_DUE", "in_app": False}]},
                   status=200)
        self.check("POST", "/api/v1/notifications/devices/register",
                   body={"token": "fcm-token-1", "platform": "ios"},
                   status=None)
        self.check("POST", "/api/v1/notifications/devices/unregister",
                   body={"token": "fcm-token-1"}, status=None)


class BankingContractTests(ContractTestCase):

    def setUp(self):
        super().setUp()
        from apps.vendors.factories import BillCategoryFactory

        BillCategoryFactory(name="Other")
        BillCategoryFactory(name="Utilities")

    def link(self):
        with self.captureOnCommitCallbacks(execute=True):
            return self.check(
                "POST", "/api/v1/banking/link/exchange",
                body={"public_token": "public-mock-chase",
                      "consent_accepted": True},
                status=201,
            ).json()["data"]

    def test_the_onboarding_flow(self):
        from apps.banking.models import BillDetectionCandidate

        self.check("GET", "/api/v1/banking/institutions", status=200)
        self.check("POST", "/api/v1/banking/link/token", body={}, status=200)
        connection = self.link()
        scan_id = connection["scan"]["id"]
        cid = connection["id"]

        self.check("GET", "/api/v1/banking/connections", status=200)
        self.check("GET", f"/api/v1/banking/connections/{cid}",
                   path="/api/v1/banking/connections/{connection_id}",
                   status=200)
        accounts = self.check("GET", "/api/v1/banking/accounts",
                              status=200).json()["data"]
        self.check("POST", "/api/v1/banking/accounts",
                   body={"account_id": accounts[0]["id"]}, status=200)

        self.check("GET", f"/api/v1/banking/scans/{scan_id}",
                   path="/api/v1/banking/scans/{scan_id}", status=200)
        self.check("GET", f"/api/v1/banking/scans/{scan_id}/candidates",
                   path="/api/v1/banking/scans/{scan_id}/candidates",
                   status=200)
        candidate = BillDetectionCandidate.objects.filter(
            scan_id=scan_id).first()
        self.check(
            "PATCH",
            f"/api/v1/banking/scans/{scan_id}/candidates/{candidate.id}",
            path="/api/v1/banking/scans/{scan_id}/candidates/{candidate_id}",
            body={"amount": "99.00"}, status=200,
        )
        self.check("POST", f"/api/v1/banking/scans/{scan_id}/import",
                   path="/api/v1/banking/scans/{scan_id}/import",
                   body={"candidate_ids": [str(candidate.id)]}, status=201)
        self.check("GET", "/api/v1/banking/onboarding-summary", status=200)

        with self.captureOnCommitCallbacks(execute=True):
            self.check("POST", "/api/v1/banking/scans",
                       body={"connection_id": cid}, status=None)

        self.check("DELETE", f"/api/v1/banking/connections/{cid}",
                   path="/api/v1/banking/connections/{connection_id}",
                   status=None)

    def test_routing_validate(self):
        self.check("POST", "/api/v1/banking/routing/validate",
                   body={"routing_number": "021000021"}, status=200)


class BillsContractTests(ContractTestCase):

    AUTH_TEXT = None

    def setUp(self):
        super().setUp()
        from apps.vendors.factories import BillCategoryFactory, VendorFactory

        self.category = BillCategoryFactory()
        self.vendor = VendorFactory(user=self.user, category=self.category)

    def create_bill(self):
        return self.check("POST", "/api/v1/bills/create", body={
            "vendor": str(self.vendor.id),
            "category": str(self.category.id),
            "bill_type": "FIXED", "amount": "3200.00",
            "frequency": "MONTHLY", "anchor_date": "2027-01-01",
            "autopay_mode": "REMIND", "source": "MANUAL",
        }, status=201).json()["data"]

    def test_bill_lifecycle(self):
        from apps.bills.models import Bill

        self.create_bill()
        bill = Bill.objects.get(user=self.user)
        bid = bill.id
        occurrence = bill.occurrences.order_by("due_date").first()

        self.check("GET", "/api/v1/bills", status=200)
        self.check("GET", "/api/v1/bills/summary", status=200)
        self.check("GET", "/api/v1/bills/next-due", status=200)
        self.check("GET", "/api/v1/bills/occurrences", status=200)
        self.check("GET", "/api/v1/bills/occurrences/upcoming", status=200)
        self.check(
            "GET", f"/api/v1/bills/occurrences/{occurrence.id}",
            path="/api/v1/bills/occurrences/{occurrence_id}", status=200,
        )
        self.check("GET", f"/api/v1/bills/{bid}/details",
                   path="/api/v1/bills/{bill_id}/details", status=200)
        self.check("GET", f"/api/v1/bills/{bid}/payments",
                   path="/api/v1/bills/{bill_id}/payments", status=200)
        self.check("GET", f"/api/v1/bills/{bid}/invoice",
                   path="/api/v1/bills/{bill_id}/invoice", status=200)
        self.check("PATCH", f"/api/v1/bills/{bid}/update",
                   path="/api/v1/bills/{bill_id}/update",
                   body={"amount": "3300.00"}, status=200)
        self.check(
            "PATCH", f"/api/v1/bills/occurrences/{occurrence.id}/pay",
            path="/api/v1/bills/occurrences/{occurrence_id}/pay",
            body={"payment_reference": "CHK-1001"}, status=200,
        )
        self.check("DELETE", f"/api/v1/bills/{bid}/details",
                   path="/api/v1/bills/{bill_id}/details", status=None)

    def test_qr_and_autopay_preview(self):
        self.check("POST", "/api/v1/bills/qr/decode", body={
            "payload": "SWAYP:vendor=WeWork;amount=3200.00;due=2026-09-01"},
            status=200)
        self.check("POST", "/api/v1/bills/qr/decode",
                   body={"payload": "@@@@"}, status=422)
        self.check("POST", "/api/v1/bills/autopay-authorization/preview",
                   body={"vendor": str(self.vendor.id), "amount": "3200.00",
                         "frequency": "MONTHLY",
                         "anchor_date": "2027-01-01"},
                   status=200)


class PaymentsContractTests(ContractTestCase):

    def setUp(self):
        super().setUp()
        import datetime as dt

        from apps.banking.factories import (
            BankAccountFactory,
            BankConnectionFactory,
        )
        from apps.bills.factories import BillFactory, BillOccurrenceFactory
        from apps.vendors.factories import VendorPaymentMethodFactory
        from integrations.money_movement.mock import MockMoneyMovementProvider

        MockMoneyMovementProvider.reset()
        BankAccountFactory(
            connection=BankConnectionFactory(user=self.user),
            is_default_funding_source=True,
        )
        self.bill = BillFactory(user=self.user,
                                anchor_date=dt.date(2026, 11, 1))
        self.bill.payment_method = VendorPaymentMethodFactory(
            vendor=self.bill.vendor)
        self.bill.save(update_fields=["payment_method"])
        self.occurrence = lambda amount="3200.00", day=1: (
            BillOccurrenceFactory(bill=self.bill, amount=amount,
                                  due_date=dt.date(2026, 11, day))
        )

    def create(self, *occurrences):
        return self.check("POST", "/api/v1/payments", body={
            "occurrence_ids": [str(o.id) for o in occurrences],
        }, status=201).json()["data"]

    def test_single_payment(self):
        occurrence = self.occurrence()
        self.check("POST", "/api/v1/payments/quote", body={
            "occurrence_ids": [str(occurrence.id)]}, status=200)
        created = self.create(occurrence)
        payment = created["payments"][0]
        pid = payment["id"]
        P = "/api/v1/payments/{payment_id}"

        self.check("PATCH", f"/api/v1/payments/{pid}", path=P,
                   body={"scheduled_for": None}, status=200)
        self.check("GET", f"/api/v1/payments/{pid}", path=P, status=200)
        with self.captureOnCommitCallbacks(execute=True):
            self.check("POST", f"/api/v1/payments/{pid}/confirm",
                       path=P + "/confirm",
                       body={"authorization_text":
                             created["authorization_text"]},
                       status=200)
        self.check("GET", f"/api/v1/payments/{pid}", path=P, status=200)
        self.check("GET", f"/api/v1/payments/{pid}/status",
                   path=P + "/status", status=200)
        self.check("GET", "/api/v1/payments/history", status=200)
        self.check("GET", f"/api/v1/bills/{self.bill.id}/payments",
                   path="/api/v1/bills/{bill_id}/payments", status=200)
        self.check("POST", f"/api/v1/payments/{pid}/cancel",
                   path=P + "/cancel", status=None)

    def test_failure_and_resolve(self):
        occurrence = self.occurrence(amount="3200.01")
        created = self.create(occurrence)
        pid = created["payments"][0]["id"]
        P = "/api/v1/payments/{payment_id}"

        with self.captureOnCommitCallbacks(execute=True):
            self.check("POST", f"/api/v1/payments/{pid}/confirm",
                       path=P + "/confirm",
                       body={"authorization_text":
                             created["authorization_text"]},
                       status=None)
        self.check("GET", f"/api/v1/payments/{pid}", path=P, status=200)
        self.check("GET", f"/api/v1/payments/{pid}/failure",
                   path=P + "/failure", status=200)
        self.check("POST", f"/api/v1/payments/{pid}/resolve",
                   path=P + "/resolve", body={"action": "retry"},
                   status=201)

    def test_batch(self):
        created = self.create(self.occurrence(day=1),
                              self.occurrence(day=15))
        bid = created["batch_id"]
        B = "/api/v1/payments/batches/{batch_id}"

        with self.captureOnCommitCallbacks(execute=True):
            self.check("POST", f"/api/v1/payments/batches/{bid}/confirm",
                       path=B + "/confirm",
                       body={"authorization_text":
                             created["authorization_text"]},
                       status=200)
        self.check("GET", f"/api/v1/payments/batches/{bid}/status",
                   path=B + "/status", status=200)
        self.check("POST", f"/api/v1/payments/batches/{bid}/cancel",
                   path=B + "/cancel", status=None)
