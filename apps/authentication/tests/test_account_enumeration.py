"""SEC-3: forgot-password, resend-otp and verify-otp answer an unknown
address exactly as they answer a registered one, and register is
rate-limited per IP."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.models import OTP, OTPPurpose

User = get_user_model()


class NeutralAnswerTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="jane@acme.com", password="Str0ng!Passphrase1",
            is_active=True, is_verified=True,
        )
        self.client = APIClient()

    def post(self, url, body):
        return self.client.post(url, body, format="json")

    def test_forgot_password_answers_the_same(self):
        known = self.post("/api/v1/auth/forgot-password",
                          {"email": "jane@acme.com"})
        unknown = self.post("/api/v1/auth/forgot-password",
                            {"email": "nobody@acme.com"})

        self.assertEqual(known.status_code, unknown.status_code, 200)
        self.assertEqual(set(known.json()), set(unknown.json()))
        self.assertIn("If an account uses", unknown.json()["message"])
        self.assertTrue(OTP.objects.filter(
            user=self.user, purpose=OTPPurpose.RESET_PASSWORD).exists())

    def test_resend_answers_the_same(self):
        body = {"purpose": "RESET_PASSWORD"}
        known = self.post("/api/v1/auth/resend-otp",
                          {**body, "email": "jane@acme.com"})
        unknown = self.post("/api/v1/auth/resend-otp",
                            {**body, "email": "nobody@acme.com"})

        self.assertEqual(known.status_code, 200)
        self.assertEqual(unknown.status_code, 200)
        import re

        def unmasked(body):
            return re.sub(r"\S+@", "X@", body["message"])

        self.assertEqual(unmasked(known.json()), unmasked(unknown.json()))

    def test_the_throttle_is_per_address_and_the_same_for_both(self):
        for email in ("jane@acme.com", "nobody@acme.com"):
            with self.subTest(email=email):
                first = self.post("/api/v1/auth/forgot-password",
                                  {"email": email})
                second = self.post("/api/v1/auth/forgot-password",
                                   {"email": email})

                self.assertEqual(first.status_code, 200)
                self.assertEqual(second.status_code, 429)
                self.assertIn("Retry-After", second)


class RegisterRateLimitTests(TestCase):

    def test_register_is_limited_per_ip(self):
        from unittest import mock

        from apps.authentication.throttles import RegisterRateThrottle

        client = APIClient()

        with mock.patch.object(
            RegisterRateThrottle, "rate", "2/hour", create=True
        ):
            codes = [
                client.post(
                    "/api/v1/auth/register", {"email": f"u{i}@x.com"},
                    format="json", HTTP_X_REAL_IP="203.0.113.5",
                ).status_code
                for i in range(3)
            ]
            other_ip = client.post(
                "/api/v1/auth/register", {"email": "z@x.com"},
                format="json", HTTP_X_REAL_IP="203.0.113.6",
            )

        self.assertEqual(codes, [400, 400, 429])
        self.assertEqual(other_ip.status_code, 400)
