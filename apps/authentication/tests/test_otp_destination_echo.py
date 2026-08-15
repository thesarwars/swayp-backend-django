"""Every endpoint that sends an OTP says where it went.

"OTP has been sent" on its own leaves the user staring at whichever inbox
they guessed at — and, on the login and resend screens, they may not remember
which address they signed up with. The address comes back masked: enough to
recognise, not enough to read off a shoulder.
"""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.authentication.models import OTPPurpose
from apps.users.models.user import User

EMAIL = "xylophone@gmail.com"
MASKED = "x***e@gmail.com"
PASSWORD = "Str0ng!Passphrase1"

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
RESEND_URL = "/api/v1/auth/resend-otp"
FORGOT_URL = "/api/v1/auth/forgot-password"

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


class DestinationEchoTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def assertMasked(self, response):
        self.assertEqual(response.data["data"]["email"], MASKED)
        self.assertIn(MASKED, response.data["message"])
        # The whole point of masking is that the raw address never ships.
        self.assertNotIn(EMAIL, str(response.data))

    def test_registration_echoes_the_masked_address(self):
        response = self.client.post(REGISTER_URL, PAYLOAD, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertMasked(response)

    def test_login_echoes_the_masked_address(self):
        self.client.post(REGISTER_URL, PAYLOAD, format="json")
        User.objects.filter(email=EMAIL).update(
            is_verified=True, is_active=True
        )

        response = self.client.post(
            LOGIN_URL,
            {"email": EMAIL, "password": PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertMasked(response)

    # The resend gap is not what this test is about, and registration has just
    # issued a code — without this the request is throttled before it answers.
    @override_settings(OTP_RESEND_MIN_GAP_SECONDS=0)
    def test_resend_echoes_the_masked_address(self):
        self.client.post(REGISTER_URL, PAYLOAD, format="json")

        response = self.client.post(
            RESEND_URL,
            {"email": EMAIL, "purpose": OTPPurpose.REGISTRATION},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertMasked(response)

    def test_forgot_password_echoes_the_masked_address(self):
        self.client.post(REGISTER_URL, PAYLOAD, format="json")

        response = self.client.post(
            FORGOT_URL, {"email": EMAIL}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertMasked(response)
