from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.authentication.services.email_services import EmailService


class EmailServiceTests(TestCase):
    @override_settings(DEFAULT_FROM_EMAIL="noreply@getswayp.com")
    @patch("apps.authentication.services.email_services.send_mail")
    def test_send_otp_email_sends_mail_with_otp(self, mock_send_mail):
        EmailService.send_otp_email("user@example.com", "123456", purpose="registration")

        self.assertEqual(mock_send_mail.call_count, 1)
        subject, message, from_email, recipient_list, kwargs = mock_send_mail.call_args.args

        self.assertIn("Verify Your Swayp Account", subject)
        self.assertIn("123456", message)
        self.assertEqual(from_email, "noreply@getswayp.com")
        self.assertEqual(recipient_list, ["user@example.com"])
        self.assertFalse(kwargs.get("fail_silently"))
