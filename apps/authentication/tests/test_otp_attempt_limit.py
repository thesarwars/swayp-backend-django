"""AUTH-11 — a code survives OTP_MAX_ATTEMPTS wrong guesses, then it is dead.

Wrong guesses were counted but never enforced, so the six digits were
guessable at leisure for the code's whole lifetime. Every path that checks a
code honours the cap, and an exhausted code is refused even for the right
guess.
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.utils.otp import TOO_MANY_ATTEMPTS, OTPService
from apps.vendors.factories import UserFactory

CODE = "123456"
WRONG = "000000"
NUMBER = "+14155552671"


@override_settings(OTP_MAX_ATTEMPTS=3)
class OTPAttemptLimitTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def _otp(self, user, purpose, **extra):
        return OTP.objects.create(
            user=user,
            code_hash=OTPService.hash_otp(CODE),
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=5),
            **extra,
        )

    def test_verify_otp_refuses_the_right_code_after_the_cap(self):
        user = UserFactory(is_active=False, is_verified=False)
        otp = self._otp(user, OTPPurpose.REGISTRATION)

        for _ in range(3):
            self.client.post(
                "/api/v1/auth/verify-otp", {"email": user.email, "otp": WRONG}
            )

        response = self.client.post(
            "/api/v1/auth/verify-otp", {"email": user.email, "otp": CODE}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["otp"], [TOO_MANY_ATTEMPTS])
        otp.refresh_from_db()
        self.assertIsNone(otp.used_at)

    def test_the_right_code_still_works_under_the_cap(self):
        user = UserFactory(is_active=False, is_verified=False)
        self._otp(user, OTPPurpose.REGISTRATION, attempts=2)

        response = self.client.post(
            "/api/v1/auth/verify-otp", {"email": user.email, "otp": CODE}
        )

        self.assertEqual(response.status_code, 200)

    def test_reset_password_counts_wrong_codes_and_stops_at_the_cap(self):
        user = UserFactory()
        otp = self._otp(user, OTPPurpose.RESET_PASSWORD)
        body = {"email": user.email, "otp": WRONG, "password": "Sw@yp-New-Pass-9"}

        for _ in range(3):
            response = self.client.post("/api/v1/auth/reset-password", body)
            self.assertEqual(response.status_code, 400)

        otp.refresh_from_db()
        self.assertEqual(otp.attempts, 3)

        response = self.client.post(
            "/api/v1/auth/reset-password", {**body, "otp": CODE}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["otp"], [TOO_MANY_ATTEMPTS])
        user.refresh_from_db()
        self.assertFalse(user.check_password("Sw@yp-New-Pass-9"))

    def test_reset_password_for_an_unknown_email_is_a_400(self):
        # Was a 500 (AUTH-8): the "no code" branch raised a bare Exception.
        response = self.client.post(
            "/api/v1/auth/reset-password",
            {
                "email": "nobody@example.com",
                "otp": CODE,
                "password": "Sw@yp-New-Pass-9",
            },
        )

        self.assertEqual(response.status_code, 400)

    def test_phone_login_stops_at_the_cap_with_the_generic_error(self):
        user = UserFactory(phone_number=NUMBER, is_active=True)
        self._otp(user, OTPPurpose.LOGIN, attempts=3)

        response = self.client.post(
            "/api/v1/auth/login/phone/verify",
            {"phone_number": NUMBER, "otp": CODE},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn(TOO_MANY_ATTEMPTS, str(response.json()))

    def test_phone_change_stops_at_the_cap(self):
        user = UserFactory()
        self._otp(user, OTPPurpose.PHONE_CHANGE, target=NUMBER, attempts=3)
        self.client.force_authenticate(user=user)

        response = self.client.post(
            "/api/v1/users/profile/phone/verify",
            {"phone_number": NUMBER, "otp": CODE},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["otp"], [TOO_MANY_ATTEMPTS])
