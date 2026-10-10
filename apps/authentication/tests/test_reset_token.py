"""AUTH-4 — a reset code can be checked before the new-password step.

verify-otp with purpose RESET_PASSWORD checks and spends the code and answers
with a reset_token. reset-password takes that token in place of the code. The
token signs nobody in, works for one account, expires, and dies the moment
the password changes.
"""

import time
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import OTP, OTPPurpose, RefreshToken
from apps.authentication.utils.otp import OTPService
from apps.vendors.factories import UserFactory

VERIFY_URL = "/api/v1/auth/verify-otp"
RESET_URL = "/api/v1/auth/reset-password"
CODE = "123456"
OLD_PASSWORD = "Sw@yp-Factory-1"
NEW_PASSWORD = "Sw@yp-New-Pass-9"


class ResetTokenTests(TestCase):

    def setUp(self):
        self.user = UserFactory(is_active=True, is_verified=True)
        self.client = APIClient()
        self.otp = OTP.objects.create(
            user=self.user,
            code_hash=OTPService.hash_otp(CODE),
            purpose=OTPPurpose.RESET_PASSWORD,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

    def _verify(self, otp=CODE, purpose="RESET_PASSWORD"):
        body = {"email": self.user.email, "otp": otp}
        if purpose:
            body["purpose"] = purpose
        return self.client.post(VERIFY_URL, body)

    def _reset(self, **body):
        return self.client.post(
            RESET_URL,
            {"email": self.user.email, "password": NEW_PASSWORD, **body},
        )

    def _token(self):
        return self._verify().json()["data"]["reset_token"]

    def test_verify_returns_a_reset_token_and_no_session(self):
        response = self._verify()

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["purpose"], "RESET_PASSWORD")
        self.assertIn("reset_token", data)
        self.assertEqual(data["expires_in"], 600)
        self.assertNotIn("access", data)
        self.assertNotIn("refresh", data)
        self.assertEqual(RefreshToken.objects.filter(user=self.user).count(), 0)

    def test_the_token_sets_the_new_password(self):
        response = self._reset(reset_token=self._token())

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))

    def test_a_wrong_code_is_caught_at_the_code_step(self):
        response = self._verify(otp="000000")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["otp"], ["Invalid OTP."])
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.attempts, 1)

    def test_the_token_is_single_use(self):
        token = self._token()
        self._reset(reset_token=token)

        response = self._reset(reset_token=token, password="Sw@yp-Other-Pass-3")

        self.assertEqual(response.status_code, 400)
        self.assertIn("reset_token", response.json()["errors"])

    def test_a_rejected_password_leaves_the_token_usable(self):
        token = self._token()

        rejected = self._reset(reset_token=token, password=OLD_PASSWORD)
        accepted = self._reset(reset_token=token)

        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(accepted.status_code, 200)

    def test_the_token_only_works_for_its_own_account(self):
        token = self._token()
        other = UserFactory()

        response = self.client.post(
            RESET_URL,
            {"email": other.email, "reset_token": token, "password": NEW_PASSWORD},
        )

        self.assertEqual(response.status_code, 400)
        other.refresh_from_db()
        self.assertFalse(other.check_password(NEW_PASSWORD))

    @override_settings(PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS=60)
    def test_the_token_expires(self):
        token = self._token()

        later = time.time() + 61

        with patch("django.core.signing.time.time", return_value=later):
            response = self._reset(reset_token=token)

        self.assertEqual(response.status_code, 400)

    def test_a_tampered_token_is_refused(self):
        response = self._reset(reset_token=self._token() + "x")

        self.assertEqual(response.status_code, 400)

    def test_the_code_alone_still_works(self):
        response = self._reset(otp=CODE)

        self.assertEqual(response.status_code, 200)

    def test_otp_and_token_together_or_neither_is_a_400(self):
        self.assertEqual(self._reset().status_code, 400)
        self.assertEqual(
            self._reset(otp=CODE, reset_token="anything").status_code, 400
        )

    def test_a_reset_code_must_be_named(self):
        # Without purpose, verify-otp only finishes registrations, so a
        # sign-up client can never be handed a reset token instead.
        response = self._verify(purpose=None)

        self.assertEqual(response.status_code, 400)
        self.otp.refresh_from_db()
        self.assertIsNone(self.otp.used_at)

    def test_a_reset_code_does_not_activate_an_unverified_account(self):
        self.user.is_verified = False
        self.user.save(update_fields=["is_verified"])

        self._verify()

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_verified)
