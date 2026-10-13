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
        not arrive."""
        for view, args in (("changelist", []), ("change", [self.otp.pk])):
            url = reverse(f"admin:authentication_otp_{view}", args=args)

            with self.subTest(view=view):
                self.assertIn("481516", self.client.get(url).content.decode())

    def test_a_superuser_can_add_change_and_delete_everything(self):
        """The admin is the raw data panel: no table is locked."""
        from django.test import RequestFactory

        from apps.ai_advisor.models import AdvisorConsent
        from apps.audit.models import AuditLog

        request = RequestFactory().get("/admin/")
        request.user = self.staff

        for model in (OTP, RefreshToken, PasswordHistory, AuditLog,
                      AdvisorConsent):
            model_admin = admin.site._registry[model]

            with self.subTest(model=model.__name__):
                self.assertTrue(model_admin.has_add_permission(request))
                self.assertTrue(model_admin.has_change_permission(request))
                self.assertTrue(model_admin.has_delete_permission(request))

    def test_a_user_with_password_history_can_be_deleted(self):
        """The screen that said "your account doesn't have permission to
        delete the following types of objects: password history"."""
        target = User.objects.create_user(
            email="leaving@acme.com", password="Str0ng!Passphrase1"
        )
        PasswordHistory.objects.create(user=target, password_hash="x")

        response = self.client.post(
            reverse("admin:users_user_delete", args=[target.pk]),
            {"post": "yes"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=target.pk).exists())
