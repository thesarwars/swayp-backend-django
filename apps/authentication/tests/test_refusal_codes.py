"""Web C8 / AUTH-3: every refusal a client branches on carries its own code,
so nothing has to match the English message."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import OTP, OTPPurpose

User = get_user_model()
PASSWORD = "Str0ng!Passphrase1"


class RefusalCodeTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="jane@acme.com", password=PASSWORD,
            is_active=True, is_verified=True,
        )

    def code(self, url, body):
        return self.client.post(url, body, format="json").json().get("code")

    def login(self, email="jane@acme.com", password=PASSWORD):
        return self.code("/api/v1/auth/login",
                         {"email": email, "password": password})

    def test_login(self):
        self.assertEqual(self.login(password="wrong"), "invalid_credentials")

        # A signup that never entered its code: inactive and unverified. It
        # was told "invalid email or password" before.
        User.objects.filter(pk=self.user.pk).update(
            is_verified=False, is_active=False)
        self.assertEqual(self.login(), "account_not_verified")

        User.objects.filter(pk=self.user.pk).update(
            is_verified=True, is_active=False)
        self.assertEqual(self.login(), "account_inactive")

        User.objects.filter(pk=self.user.pk).update(
            is_active=True, locked_until=timezone.now() + timedelta(minutes=5))
        self.assertEqual(self.login(), "account_locked")

    def otp(self, code="123456", minutes=5, attempts=0):
        OTP.objects.filter(user=self.user).delete()
        return OTP.objects.create(
            user=self.user, code=code, purpose=OTPPurpose.RESET_PASSWORD,
            expires_at=timezone.now() + timedelta(minutes=minutes),
            attempts=attempts,
        )

    def verify(self, code):
        return self.code("/api/v1/auth/verify-otp", {
            "email": "jane@acme.com", "otp": code,
            "purpose": "RESET_PASSWORD"})

    def test_codes(self):
        self.assertEqual(self.verify("000000"), "otp_not_pending")

        self.otp()
        self.assertEqual(self.verify("000000"), "otp_invalid")

        self.otp(minutes=-1)
        self.assertEqual(self.verify("123456"), "otp_expired")

        self.otp(attempts=99)
        self.assertEqual(self.verify("123456"), "otp_attempts_exceeded")

    def test_reset_with_a_bad_token(self):
        self.assertEqual(self.code("/api/v1/auth/reset-password", {
            "email": "jane@acme.com", "reset_token": "nope",
            "password": "An0ther!Passphrase2"}), "reset_token_invalid")

    def test_register_with_a_taken_email(self):
        self.assertEqual(self.code("/api/v1/auth/register", {
            "first_name": "J", "last_name": "S", "email": "jane@acme.com",
            "business_name": "A", "password": PASSWORD,
            "terms_accepted": True}), "email_taken")

    def test_subscribing_twice(self):
        self.client.force_authenticate(user=self.user)
        self.code("/api/v1/billing/subscription", {"plan": "STANDARD"})

        self.assertEqual(
            self.code("/api/v1/billing/subscription", {"plan": "STANDARD"}),
            "already_subscribed",
        )
