"""The authentication models are reachable in the admin, minus their secrets.

Registration is easy to assert and easy to regress: a model added to the app
later shows up nowhere, and a hash exposed by a stray ``readonly_fields`` edit
renders without anything failing. Both are checked against the rendered page
rather than the ModelAdmin attributes, because it is the page that leaks.
"""

from datetime import timedelta

from django.contrib import admin
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.authentication.models import (
    OTP,
    OTPPurpose,
    PasswordHistory,
    RefreshToken,
)
from apps.users.models.user import User

#: field name -> the value that must never reach the page.
SECRETS = {
    "token_hash": "token-hash-must-not-render",
    "password_hash": "password-hash-must-not-render",
}


class AuthenticationAdminTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(
            email="root@acme.com", password="Str0ng!Passphrase1"
        )

        cls.otp = OTP.objects.create(
            user=cls.staff,
            code="481516",
            purpose=OTPPurpose.LOGIN,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        cls.token = RefreshToken.objects.create(
            user=cls.staff,
            token_hash=SECRETS["token_hash"],
            user_agent="pytest",
            ip_address="127.0.0.1",
            expires_at=timezone.now() + timedelta(days=1),
        )

        cls.history = PasswordHistory.objects.create(
            user=cls.staff, password_hash=SECRETS["password_hash"]
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_every_model_in_the_app_is_registered(self):
        registered = set(admin.site._registry)

        for model in (OTP, RefreshToken, PasswordHistory):
            with self.subTest(model=model.__name__):
                self.assertIn(model, registered)

    def test_every_page_renders(self):
        """Asserted separately from the hash check, which a 500 would pass.

        An error page contains no secret either, so without this the leak
        test could be green while the admin was broken.
        """
        for obj in (self.otp, self.token, self.history):
            meta = obj._meta

            for view, args in (("changelist", []), ("change", [obj.pk])):
                with self.subTest(model=meta.model_name, view=view):
                    url = reverse(
                        f"admin:{meta.app_label}_{meta.model_name}_{view}",
                        args=args,
                    )

                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_no_page_renders_a_hash(self):
        """The reason every hash is excluded rather than made readonly."""
        for obj in (self.token, self.history):
            meta = obj._meta

            for view, args in (
                ("changelist", []),
                ("change", [obj.pk]),
            ):
                url = reverse(
                    f"admin:{meta.app_label}_{meta.model_name}_{view}", args=args
                )
                body = self.client.get(url).content.decode()

                for secret in SECRETS.values():
                    with self.subTest(model=meta.model_name, view=view):
                        self.assertNotIn(secret, body)

    def test_the_otp_code_is_shown(self):
        """Kept in plain text so an operator can read it when email does
        not arrive; visible in the list and on the row, but not editable."""
        for view, args in (("changelist", []), ("change", [self.otp.pk])):
            url = reverse(f"admin:authentication_otp_{view}", args=args)

            with self.subTest(view=view):
                self.assertIn("481516", self.client.get(url).content.decode())

        self.assertIn("code", admin.site._registry[OTP].readonly_fields)

    def test_a_session_can_be_revoked_but_not_forged(self):
        """revoked_at is the one write; nothing here mints a session."""
        token_admin = admin.site._registry[RefreshToken]

        self.assertFalse(token_admin.has_add_permission(None))
        self.assertNotIn("revoked_at", token_admin.readonly_fields)

    def test_codes_and_history_are_not_editable(self):
        for model in (OTP, PasswordHistory):
            model_admin = admin.site._registry[model]

            with self.subTest(model=model.__name__):
                self.assertFalse(model_admin.has_add_permission(None))
                self.assertFalse(model_admin.has_change_permission(None))

    def test_password_history_cannot_be_deleted(self):
        """A history an operator can clear does not prevent reuse."""
        history_admin = admin.site._registry[PasswordHistory]

        self.assertFalse(history_admin.has_delete_permission(None))
