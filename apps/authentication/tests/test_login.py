"""Login is one step: a correct password returns the tokens.

It used to mail a code and hand the tokens out on a second call. The code
arrived in the same inbox that a password reset lands in, so it added a step to
every sign-in without adding a factor anyone had to hold separately.

The gates in front of it are unchanged — locked, inactive and unverified
accounts are still refused — which is what makes removing the second call a
change to the number of round trips rather than to who gets in.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.models import OTP, OTPPurpose, RefreshToken
from apps.users.models.user import User

LOGIN_URL = "/api/v1/auth/login"
REGISTER_URL = "/api/v1/auth/register"

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


class LoginTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.post(REGISTER_URL, PAYLOAD, format="json")

        self.user = User.objects.get(email=EMAIL)
        User.objects.filter(pk=self.user.pk).update(
            is_verified=True, is_active=True
        )

        OTP.objects.filter(user=self.user).delete()

    def login(self, password=PASSWORD, **extra):
        return self.client.post(
            LOGIN_URL,
            {"email": EMAIL, "password": password},
            format="json",
            **extra,
        )

    def test_a_correct_password_returns_tokens(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["message"], "Login successful.")
        self.assertIn("access", response.data["data"])
        self.assertIn("refresh", response.data["data"])

    def test_no_code_is_issued(self):
        """The whole point. A mailed code here is a step nobody needs."""
        self.login()

        self.assertFalse(
            OTP.objects.filter(
                user=self.user, purpose=OTPPurpose.LOGIN
            ).exists()
        )

    def test_the_session_is_recorded(self):
        """Recording moved with the tokens.

        It used to happen on the verify call. If it had been left behind, every
        session would be unrevocable and unattributable — and nothing else
        would have looked wrong.
        """
        self.login(HTTP_USER_AGENT="pytest-agent")

        session = RefreshToken.objects.get(user=self.user)

        self.assertEqual(session.user_agent, "pytest-agent")
        self.assertIsNotNone(session.ip_address)
        self.assertIsNone(session.revoked_at)

    def test_the_refresh_token_is_not_stored_in_the_clear(self):
        response = self.login()

        session = RefreshToken.objects.get(user=self.user)

        self.assertNotEqual(
            session.token_hash, response.data["data"]["refresh"]
        )

    def test_a_wrong_password_is_refused(self):
        response = self.login(password="wrong")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(RefreshToken.objects.filter(user=self.user).exists())

    def test_an_unverified_account_is_still_refused(self):
        """Registration still has to be finished; only the login code is gone."""
        User.objects.filter(pk=self.user.pk).update(is_verified=False)

        response = self.login()

        self.assertEqual(response.status_code, 400)
        self.assertIn("not verified", str(response.data).lower())

    def test_an_inactive_account_is_still_refused(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        response = self.login()

        self.assertEqual(response.status_code, 400)
