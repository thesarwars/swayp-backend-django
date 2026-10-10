"""/auth/verify-otp — the one endpoint that spends an emailed code.

It finishes a registration and nothing else. Login used to have a code of its
own and a second endpoint to spend it at; both are gone, and the test that used
to prove a login code worked here now proves it does not. That inversion is the
point: /auth/resend-otp will mail a LOGIN code to any registered address, so a
verify that still accepted one would hand out tokens for possession of the
inbox and make the password optional again.
"""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from rest_framework.test import APIClient

from apps.authentication.models import OTP, OTPPurpose, RefreshToken
from apps.authentication.utils.otp import OTPService
from apps.users.models.user import User

VERIFY_URL = "/api/v1/auth/verify-otp"
REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"

EMAIL = "jane@acme.com"
PASSWORD = "Str0ng!Passphrase1"

PAYLOAD = {
    "first_name": "Jane",
    "last_name": "Smith",
    "email": EMAIL,
    "business_name": "Acme Corporation, LLC",
    "industry": "Construction",
    "business_size": "11-50",
    "password": PASSWORD,
    "terms_accepted": True,
    "signatory_confirmed": True,
}


class MergedVerifyTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    # -- helpers ----------------------------------------------------------

    def register(self):
        self.client.post(REGISTER_URL, PAYLOAD, format="json")

        return User.objects.get(email=EMAIL)

    def issue(self, user, purpose, code="123456", minutes=5):
        """Write a code directly — the real one is only ever emailed."""
        return OTP.objects.create(
            user=user,
            code_hash=OTPService.hash_otp(code),
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=minutes),
        )

    def verify(self, **extra):
        return self.client.post(
            VERIFY_URL, {"email": EMAIL, **extra}, format="json"
        )

    # -- the two flows, one URL -------------------------------------------

    def test_a_registration_code_verifies_the_account(self):
        user = self.register()
        OTP.objects.filter(user=user).delete()
        self.issue(user, OTPPurpose.REGISTRATION, code="111111")

        response = self.verify(otp="111111")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["purpose"], "REGISTRATION")
        self.assertIn("access", response.data["data"])

        user.refresh_from_db()
        self.assertTrue(user.is_verified)

    def test_a_login_code_is_refused(self):
        """The door that would make the password optional.

        resend-otp will mail a LOGIN code to any registered address. If this
        endpoint spent one, an inbox alone would be enough to sign in — and the
        inbox is where a password reset lands too.
        """
        user = self.register()
        OTP.objects.filter(user=user).delete()
        User.objects.filter(pk=user.pk).update(
            is_verified=True, is_active=True
        )
        login_code = self.issue(user, OTPPurpose.LOGIN, code="222222")

        response = self.verify(otp="222222")

        self.assertEqual(response.status_code, 400)

        login_code.refresh_from_db()
        self.assertIsNone(login_code.used_at)
        self.assertEqual(RefreshToken.objects.filter(user=user).count(), 0)

    def test_naming_the_login_purpose_is_refused_by_name(self):
        """A clearer answer than searching and finding nothing."""
        user = self.register()
        OTP.objects.filter(user=user).delete()
        self.issue(user, OTPPurpose.LOGIN, code="333333")

        response = self.verify(otp="333333", purpose="LOGIN")

        self.assertEqual(response.status_code, 400)
        self.assertIn("purpose", response.data["errors"])

    def test_a_registration_code_records_no_session(self):
        user = self.register()
        OTP.objects.filter(user=user).delete()
        self.issue(user, OTPPurpose.REGISTRATION, code="444444")

        self.verify(otp="444444")

        self.assertEqual(RefreshToken.objects.filter(user=user).count(), 0)

    # -- picking the right row --------------------------------------------

    def test_the_code_picks_its_own_row(self):
        """Matched by hash, not by "whichever row is newest".

        Issuing deletes the previous unused code of the same purpose, so today
        there is only ever one to match. The lookup does not lean on that: an
        older live code still verifies if a second one exists.
        """
        user = self.register()
        OTP.objects.filter(user=user).delete()
        self.issue(user, OTPPurpose.REGISTRATION, code="555555")
        self.issue(user, OTPPurpose.REGISTRATION, code="666666")

        response = self.verify(otp="555555")

        self.assertEqual(response.status_code, 200)

    def test_reset_password_codes_are_not_verifiable_here(self):
        """Not without naming the purpose.

        A request without ``purpose`` only finishes a registration, so a
        sign-up client can never spend a reset code by accident. Naming
        RESET_PASSWORD is covered in test_reset_token.py.
        """
        user = self.register()
        OTP.objects.filter(user=user).delete()
        self.issue(user, OTPPurpose.RESET_PASSWORD, code="888888")

        response = self.verify(otp="888888")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            OTP.objects.get(user=user, purpose=OTPPurpose.RESET_PASSWORD).used_at,
            None,
        )

    # -- what the failures say --------------------------------------------

    def test_an_already_used_code_says_so(self):
        user = self.register()
        OTP.objects.filter(user=user).delete()
        self.issue(user, OTPPurpose.REGISTRATION, code="999999")

        self.verify(otp="999999")
        response = self.verify(otp="999999")

        self.assertEqual(response.status_code, 400)
        self.assertIn("used already", str(response.data["errors"]["otp"]))

    def test_an_unverified_account_with_no_code_is_told_to_request_one(self):
        user = self.register()
        OTP.objects.filter(user=user).delete()

        response = self.verify(otp="000000")

        self.assertEqual(response.status_code, 400)
        self.assertIn("finish signing up", str(response.data["errors"]["otp"]))

    def test_an_expired_code_says_expired_not_missing(self):
        user = self.register()
        OTP.objects.filter(user=user).delete()
        self.issue(user, OTPPurpose.REGISTRATION, code="121212", minutes=-1)

        response = self.verify(otp="121212")

        self.assertEqual(response.status_code, 400)
        self.assertIn("expired", str(response.data["errors"]["otp"]).lower())

    def test_a_wrong_code_counts_against_the_newest_row(self):
        user = self.register()
        OTP.objects.filter(user=user).delete()
        otp = self.issue(user, OTPPurpose.REGISTRATION, code="131313")

        response = self.verify(otp="141414")

        self.assertEqual(response.status_code, 400)
        otp.refresh_from_db()
        self.assertEqual(otp.attempts, 1)

    # -- the old route is gone --------------------------------------------

    @override_settings(OTP_RESEND_MIN_GAP_SECONDS=0)
    def test_the_login_verify_route_no_longer_exists(self):
        self.register()
        User.objects.filter(email=EMAIL).update(
            is_verified=True, is_active=True
        )
        self.client.post(
            LOGIN_URL, {"email": EMAIL, "password": PASSWORD}, format="json"
        )

        response = self.client.post(
            "/api/v1/auth/login/verify",
            {"email": EMAIL, "otp": "123456"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
