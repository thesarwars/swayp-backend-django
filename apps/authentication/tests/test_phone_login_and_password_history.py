"""Phone login and password reuse prevention (E2-S3 / E2-S4)."""

from datetime import timedelta

from django.contrib.auth.hashers import check_password
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.authentication.models import (
    OTP,
    OTPPurpose,
    PasswordHistory,
)
from apps.authentication.services.password_history_service import (
    PasswordHistoryService,
)
from apps.authentication.utils.otp import OTPService
from apps.users.models import User

PASSWORD = "Sw@yp-Test-1"


@override_settings(MESSAGING_PROVIDER="mock")
class PhoneLoginTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="phone@example.com",
            phone_number="+15551234567",
            password=PASSWORD,
        )
        # create_user leaves accounts unverified/inactive until OTP
        # confirmation; phone login only applies to active accounts.
        self.user.is_active = True
        self.user.save(update_fields=["is_active"])
        self.client = APIClient()

    def request_code(self, phone_number):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                "/api/v1/auth/login/phone/request/",
                {"phone_number": phone_number},
                format="json",
            )

    def test_request_issues_a_login_otp(self):
        response = self.request_code("+15551234567")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            OTP.objects.filter(
                user=self.user, purpose=OTPPurpose.LOGIN
            ).exists()
        )

    def test_request_reuses_the_login_purpose(self):
        self.request_code("+15551234567")

        self.assertEqual(
            OTP.objects.get(user=self.user).purpose, OTPPurpose.LOGIN
        )

    def test_unknown_number_gets_the_same_response(self):
        known = self.request_code("+15551234567")
        unknown = self.request_code("+15559999999")

        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.data["message"], unknown.data["message"])

    def test_unknown_number_creates_no_otp(self):
        self.request_code("+15559999999")

        self.assertEqual(OTP.objects.count(), 0)

    def test_verify_exchanges_a_code_for_tokens(self):
        code = OTPService.generate_otp()
        OTP.objects.create(
            user=self.user,
            code_hash=OTPService.hash_otp(code),
            purpose=OTPPurpose.LOGIN,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = self.client.post(
            "/api/v1/auth/login/phone/verify/",
            {"phone_number": "+15551234567", "otp": code},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data["data"])
        self.assertIn("refresh", response.data["data"])

    def test_verify_with_an_unknown_number_does_not_enumerate(self):
        code = OTPService.generate_otp()
        OTP.objects.create(
            user=self.user,
            code_hash=OTPService.hash_otp(code),
            purpose=OTPPurpose.LOGIN,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        unknown = self.client.post(
            "/api/v1/auth/login/phone/verify/",
            {"phone_number": "+15559999999", "otp": code},
            format="json",
        )
        wrong_code = self.client.post(
            "/api/v1/auth/login/phone/verify/",
            {"phone_number": "+15551234567", "otp": "000000"},
            format="json",
        )

        self.assertEqual(unknown.status_code, wrong_code.status_code)
        self.assertEqual(unknown.data["message"], wrong_code.data["message"])

    def test_expired_code_is_refused(self):
        code = OTPService.generate_otp()
        OTP.objects.create(
            user=self.user,
            code_hash=OTPService.hash_otp(code),
            purpose=OTPPurpose.LOGIN,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.post(
            "/api/v1/auth/login/phone/verify/",
            {"phone_number": "+15551234567", "otp": code},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_used_code_cannot_be_replayed(self):
        code = OTPService.generate_otp()
        OTP.objects.create(
            user=self.user,
            code_hash=OTPService.hash_otp(code),
            purpose=OTPPurpose.LOGIN,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        payload = {"phone_number": "+15551234567", "otp": code}

        self.assertEqual(
            self.client.post(
                "/api/v1/auth/login/phone/verify/", payload, format="json"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/login/phone/verify/", payload, format="json"
            ).status_code,
            400,
        )


class PasswordHistoryTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="pw@example.com", password=PASSWORD
        )
        self.service = PasswordHistoryService()

    def test_recording_stores_the_current_hash(self):
        self.service.record(user=self.user)

        entry = PasswordHistory.objects.get(user=self.user)
        self.assertTrue(check_password(PASSWORD, entry.password_hash))

    def test_reusing_the_current_password_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.service.assert_not_reused(
                user=self.user, raw_password=PASSWORD
            )

    def test_a_new_password_is_accepted(self):
        self.service.assert_not_reused(
            user=self.user, raw_password="Sw@yp-Different-9"
        )

    def test_reusing_a_recorded_password_is_rejected(self):
        self.service.record(user=self.user)
        self.user.set_password("Sw@yp-Second-2")
        self.user.save(update_fields=["password"])

        with self.assertRaises(ValidationError):
            self.service.assert_not_reused(
                user=self.user, raw_password=PASSWORD
            )

    @override_settings(PASSWORD_HISTORY_KEEP=3)
    def test_history_is_pruned(self):
        for index in range(6):
            self.user.set_password(f"Sw@yp-Rotate-{index}")
            self.user.save(update_fields=["password"])
            self.service.record(user=self.user)

        self.assertEqual(
            PasswordHistory.objects.filter(user=self.user).count(), 3
        )

    def test_reset_rejects_the_previous_password(self):
        from apps.authentication.services.reset_password_service import (
            ResetPasswordService,
        )

        code = OTPService.generate_otp()
        OTP.objects.create(
            user=self.user,
            code_hash=OTPService.hash_otp(code),
            purpose=OTPPurpose.RESET_PASSWORD,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        with self.assertRaises(ValidationError):
            ResetPasswordService.reset(
                self.user.email, code, PASSWORD
            )

    def test_a_rejected_reset_leaves_the_code_usable(self):
        from apps.authentication.services.reset_password_service import (
            ResetPasswordService,
        )

        code = OTPService.generate_otp()
        otp = OTP.objects.create(
            user=self.user,
            code_hash=OTPService.hash_otp(code),
            purpose=OTPPurpose.RESET_PASSWORD,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        with self.assertRaises(ValidationError):
            ResetPasswordService.reset(self.user.email, code, PASSWORD)

        otp.refresh_from_db()
        self.assertIsNone(otp.used_at)

        # The same code still works for an acceptable password.
        ResetPasswordService.reset(
            self.user.email, code, "Sw@yp-Brand-New-7"
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Sw@yp-Brand-New-7"))

    def test_a_successful_reset_records_the_old_hash(self):
        from apps.authentication.services.reset_password_service import (
            ResetPasswordService,
        )

        code = OTPService.generate_otp()
        OTP.objects.create(
            user=self.user,
            code_hash=OTPService.hash_otp(code),
            purpose=OTPPurpose.RESET_PASSWORD,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        ResetPasswordService.reset(
            self.user.email, code, "Sw@yp-Brand-New-7"
        )

        entry = PasswordHistory.objects.filter(user=self.user).first()
        self.assertTrue(check_password(PASSWORD, entry.password_hash))
