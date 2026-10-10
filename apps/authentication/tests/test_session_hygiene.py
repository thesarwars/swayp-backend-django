"""SEC-5: one account per address whatever its case, and a password reset
ends every session."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import OTP, OTPPurpose, RefreshToken
from apps.authentication.utils.otp import OTPService

User = get_user_model()
PASSWORD = "Str0ng!Passphrase1"


class EmailCaseTests(TestCase):

    def test_addresses_are_stored_lowercased_on_every_path(self):
        created = User.objects.create_user(email="Jane@Acme.COM", password=PASSWORD)
        self.assertEqual(created.email, "jane@acme.com")

        created.email = "JANE@acme.com"
        created.save()
        created.refresh_from_db()
        self.assertEqual(created.email, "jane@acme.com")

    def test_a_second_account_differing_only_in_case_is_refused(self):
        User.objects.create_user(email="jane@acme.com", password=PASSWORD)

        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.bulk_create([User(email="JANE@acme.com")])

    def test_sign_in_ignores_case(self):
        User.objects.create_user(
            email="jane@acme.com", password=PASSWORD,
            is_active=True, is_verified=True,
        )

        response = APIClient().post(
            "/api/v1/auth/login",
            {"email": "Jane@ACME.com", "password": PASSWORD}, format="json",
        )

        self.assertEqual(response.status_code, 200)


class ResetEndsSessionsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="jane@acme.com", password=PASSWORD,
            is_active=True, is_verified=True,
        )
        self.client = APIClient()
        self.tokens = self.client.post(
            "/api/v1/auth/login",
            {"email": "jane@acme.com", "password": PASSWORD}, format="json",
        ).json()["data"]

    def test_a_reset_revokes_and_blacklists_every_refresh_token(self):
        OTP.objects.create(
            user=self.user, code_hash=OTPService.hash_otp("123456"),
            purpose=OTPPurpose.RESET_PASSWORD,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        response = self.client.post("/api/v1/auth/reset-password", {
            "email": "jane@acme.com", "otp": "123456",
            "password": "An0ther!Passphrase2",
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            RefreshToken.objects.filter(
                user=self.user, revoked_at__isnull=True).exists()
        )
        refresh = self.client.post(
            "/api/v1/auth/refresh", {"refresh": self.tokens["refresh"]},
            format="json",
        )
        self.assertEqual(refresh.status_code, 401)
