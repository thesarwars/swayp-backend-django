"""Emails that tell a user their account's protection changed."""

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.tasks import _NOTICES, send_security_notice
from apps.users.models.user import User

PASSWORD = "Str0ng!Passphrase1"
DELAY = "apps.authentication.tasks.send_security_notice.delay"


class PasswordChangedNoticeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="jane@acme.com", password=PASSWORD,
            is_active=True, is_verified=True,
        )
        self.client = APIClient()

    def test_changing_the_password_emails_the_user(self):
        self.client.force_authenticate(user=self.user)

        with mock.patch(DELAY) as delay, self.captureOnCommitCallbacks(
            execute=True
        ):
            response = self.client.post(
                "/api/v1/users/password",
                {
                    "current_password": PASSWORD,
                    "new_password": "An0ther!Passphrase2",
                },
                format="json",
            )

        self.assertEqual(response.status_code, 200, response.data)
        delay.assert_called_once_with(
            destination="jane@acme.com", kind="PASSWORD_CHANGED"
        )

    def test_resetting_the_password_emails_the_user(self):
        OTP.objects.create(
            user=self.user, code="123456",
            purpose=OTPPurpose.RESET_PASSWORD,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        with mock.patch(DELAY) as delay, self.captureOnCommitCallbacks(
            execute=True
        ):
            response = self.client.post("/api/v1/auth/reset-password", {
                "email": "jane@acme.com", "otp": "123456",
                "password": "An0ther!Passphrase2",
            }, format="json")

        self.assertEqual(response.status_code, 200, response.data)
        delay.assert_called_once_with(
            destination="jane@acme.com", kind="PASSWORD_CHANGED"
        )

    def test_a_wrong_current_password_sends_nothing(self):
        self.client.force_authenticate(user=self.user)

        with mock.patch(DELAY) as delay, self.captureOnCommitCallbacks(
            execute=True
        ):
            self.client.post(
                "/api/v1/users/password",
                {"current_password": "wrong", "new_password": "An0ther!Pass2"},
                format="json",
            )

        delay.assert_not_called()


class NoticeDeliveryTests(TestCase):

    def test_every_notice_says_what_to_do_if_it_was_not_you(self):
        for kind, (subject, body) in _NOTICES.items():
            with self.subTest(kind=kind):
                self.assertTrue(subject)
                self.assertIn("If this wasn't you", body)

    def test_the_task_sends_through_the_messaging_provider(self):
        provider = mock.Mock()
        provider.send.return_value = mock.Mock(delivered=True)

        with mock.patch(
            "apps.authentication.tasks.get_messaging_provider",
            return_value=provider,
        ):
            send_security_notice(destination="a@b.com", kind="PASSWORD_CHANGED")

        message = provider.send.call_args.args[0]
        self.assertEqual(message.to, "a@b.com")
        self.assertEqual(message.subject, "Your Swayp password was changed")
