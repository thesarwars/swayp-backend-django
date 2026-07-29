"""OTP channel, async delivery and resend throttling (E2-S1 / E2-S2)."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from apps.common.exceptions import ChannelNotAvailableException

from apps.authentication.models import OTP, OTPChannel, OTPPurpose
from apps.authentication.services.otp_delivery_service import (
    OTPDeliveryService,
    validate_channel,
)
from apps.authentication.services.otp_throttle_service import (
    OTPThrottleService,
)
from apps.authentication.tasks import render, send_otp
from apps.common.exceptions import OTPThrottledException
from apps.users.models import User
from integrations.factory import get_messaging_provider
from integrations.messaging.base import ChannelNotSupported, Message
from integrations.messaging.mock import MockMessagingProvider


@override_settings(MESSAGING_PROVIDER="mock")
class ChannelTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="otp@example.com", password="Sw@yp-Test-1"
        )

    def test_email_is_the_default_channel(self):
        otp = OTPDeliveryService().issue(
            user=self.user, purpose=OTPPurpose.REGISTRATION
        )

        self.assertEqual(otp.channel, OTPChannel.EMAIL)

    def test_sms_is_rejected_rather_than_silently_ignored(self):
        # 501, not 400: the request is well-formed, SMS just is not
        # implemented this release.
        with self.assertRaises(ChannelNotAvailableException):
            validate_channel(OTPChannel.SMS)

    def test_issuing_on_sms_is_rejected(self):
        with self.assertRaises(ChannelNotAvailableException):
            OTPDeliveryService().issue(
                user=self.user,
                purpose=OTPPurpose.LOGIN,
                channel=OTPChannel.SMS,
            )

        self.assertEqual(OTP.objects.count(), 0)

    def test_mock_provider_refuses_sms(self):
        with self.assertRaises(ChannelNotSupported):
            MockMessagingProvider().send(
                Message(to="x@example.com", subject="s", body="b",
                        channel="SMS")
            )

    def test_provider_resolves_from_settings(self):
        self.assertIsInstance(get_messaging_provider(), MockMessagingProvider)


@override_settings(MESSAGING_PROVIDER="mock")
class DeliveryTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="deliver@example.com", password="Sw@yp-Test-1"
        )

    def test_issuing_replaces_any_live_code(self):
        service = OTPDeliveryService()

        service.issue(user=self.user, purpose=OTPPurpose.LOGIN)
        service.issue(user=self.user, purpose=OTPPurpose.LOGIN)

        self.assertEqual(
            OTP.objects.filter(
                user=self.user, purpose=OTPPurpose.LOGIN, used_at__isnull=True
            ).count(),
            1,
        )

    def issue_capturing_dispatch(self, purpose):
        """Issue an OTP and return (otp, queued mock).

        Dispatch is registered with transaction.on_commit, which never fires
        inside TestCase's rollback wrapper — captureOnCommitCallbacks runs it.
        """
        with patch("apps.authentication.tasks.send_otp.delay") as queued:
            with self.captureOnCommitCallbacks(execute=True):
                otp = OTPDeliveryService().issue(
                    user=self.user, purpose=purpose
                )

        return otp, queued

    def test_delivery_is_queued_not_inline(self):
        _, queued = self.issue_capturing_dispatch(OTPPurpose.REGISTRATION)

        self.assertEqual(queued.call_count, 1)
        kwargs = queued.call_args.kwargs
        self.assertEqual(kwargs["destination"], "deliver@example.com")
        self.assertEqual(kwargs["channel"], OTPChannel.EMAIL)

    def test_dispatch_waits_for_commit(self):
        """Queuing before commit would race the worker against the OTP row."""
        with patch("apps.authentication.tasks.send_otp.delay") as queued:
            OTPDeliveryService().issue(
                user=self.user, purpose=OTPPurpose.LOGIN
            )
            self.assertEqual(queued.call_count, 0)

    def test_the_raw_code_is_never_stored(self):
        otp, queued = self.issue_capturing_dispatch(OTPPurpose.LOGIN)

        code = queued.call_args.kwargs["code"]

        self.assertNotEqual(otp.code_hash, code)
        self.assertNotIn(code, otp.code_hash)

    def test_task_delivers_through_the_provider(self):
        result = send_otp(
            destination="deliver@example.com",
            code="123456",
            purpose="LOGIN",
            channel="EMAIL",
        )

        self.assertEqual(result, "MOCK-MSG-EMAIL")

    def test_task_does_not_retry_an_unsupported_channel(self):
        with self.assertRaises(ChannelNotSupported):
            send_otp(
                destination="deliver@example.com",
                code="123456",
                purpose="LOGIN",
                channel="SMS",
            )

    def test_templates_differ_per_purpose_and_carry_the_code(self):
        for purpose, marker in [
            ("REGISTRATION", "Verify Your Swayp Account"),
            ("LOGIN", "Login OTP"),
            ("RESET_PASSWORD", "Reset Your Swayp Password"),
        ]:
            with self.subTest(purpose=purpose):
                subject, body = render(purpose, "654321")
                self.assertIn(marker, subject)
                self.assertIn("654321", body)


@override_settings(
    MESSAGING_PROVIDER="mock",
    OTP_RESEND_MIN_GAP_SECONDS=60,
    OTP_RESEND_HOURLY_LIMIT=5,
)
class ThrottleTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="throttle@example.com", password="Sw@yp-Test-1"
        )
        self.throttle = OTPThrottleService()

    def make_otp(self, age_seconds=0):
        otp = OTP.objects.create(
            user=self.user,
            code_hash="x",
            purpose=OTPPurpose.LOGIN,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        if age_seconds:
            OTP.objects.filter(pk=otp.pk).update(
                created_at=timezone.now() - timedelta(seconds=age_seconds)
            )
        return otp

    def test_first_request_passes(self):
        self.assertEqual(
            self.throttle.check(user=self.user, purpose=OTPPurpose.LOGIN), 0
        )

    def test_second_request_inside_the_gap_is_throttled(self):
        self.make_otp()

        with self.assertRaises(OTPThrottledException) as ctx:
            self.throttle.check(user=self.user, purpose=OTPPurpose.LOGIN)

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertGreater(ctx.exception.retry_after, 0)

    def test_request_after_the_gap_passes(self):
        self.make_otp(age_seconds=61)

        self.assertEqual(
            self.throttle.check(user=self.user, purpose=OTPPurpose.LOGIN), 0
        )

    def test_hourly_cap_is_enforced(self):
        for index in range(5):
            self.make_otp(age_seconds=61 + index * 60)

        with self.assertRaises(OTPThrottledException):
            self.throttle.check(user=self.user, purpose=OTPPurpose.LOGIN)

    def test_the_cap_is_scoped_per_purpose(self):
        for index in range(5):
            self.make_otp(age_seconds=61 + index * 60)

        # A different purpose has its own budget.
        self.assertEqual(
            self.throttle.check(
                user=self.user, purpose=OTPPurpose.RESET_PASSWORD
            ),
            0,
        )

    def test_codes_older_than_an_hour_leave_the_window(self):
        for index in range(5):
            self.make_otp(age_seconds=3700 + index * 60)

        self.assertEqual(
            self.throttle.check(user=self.user, purpose=OTPPurpose.LOGIN), 0
        )

    def test_a_throttled_resend_leaves_the_existing_code_alone(self):
        from apps.authentication.services.resend_otp_service import (
            ResendOTPService,
        )

        existing = self.make_otp()

        with self.assertRaises(OTPThrottledException):
            ResendOTPService.resend(self.user, OTPPurpose.LOGIN)

        self.assertTrue(OTP.objects.filter(pk=existing.pk).exists())

    def test_retry_after_reaches_the_response_header(self):
        from rest_framework.test import APIClient

        self.make_otp()

        client = APIClient()
        response = client.post(
            "/api/v1/auth/resend-otp/",
            {"email": "throttle@example.com", "purpose": "LOGIN"},
            format="json",
        )

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)


@override_settings(MESSAGING_PROVIDER="mock")
class BrokerOutageTests(TestCase):
    """A dead broker must not cost the user their code."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="outage@example.com", password="Sw@yp-Test-1"
        )

    def test_a_failed_queue_falls_back_to_sending_inline(self):
        service = OTPDeliveryService()

        with patch(
            "apps.authentication.tasks.send_otp.delay",
            side_effect=OSError("broker unreachable"),
        ):
            with patch(
                "apps.authentication.tasks.send_otp",
                wraps=send_otp,
            ) as inline:
                service._queue_or_send(
                    destination="outage@example.com",
                    code="123456",
                    purpose="REGISTRATION",
                    channel="EMAIL",
                )

        self.assertEqual(inline.call_count, 1)

    def test_registration_still_delivers_when_the_broker_is_down(self):
        with patch(
            "apps.authentication.tasks.send_otp.delay",
            side_effect=OSError("broker unreachable"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                OTPDeliveryService().issue(
                    user=self.user, purpose=OTPPurpose.REGISTRATION
                )

        # The code exists and delivery was attempted rather than dropped.
        self.assertEqual(
            OTP.objects.filter(
                user=self.user, purpose=OTPPurpose.REGISTRATION
            ).count(),
            1,
        )

    def test_a_broker_outage_is_logged_at_error_level(self):
        with patch(
            "apps.authentication.tasks.send_otp.delay",
            side_effect=OSError("broker unreachable"),
        ):
            with self.assertLogs(
                "apps.authentication.services.otp_delivery_service",
                level="ERROR",
            ) as captured:
                OTPDeliveryService()._queue_or_send(
                    destination="outage@example.com",
                    code="123456",
                    purpose="LOGIN",
                    channel="EMAIL",
                )

        self.assertIn("Check the Celery broker", captured.output[0])

    def test_an_undeliverable_address_still_raises(self):
        """The fallback must not turn a real failure into a false success."""
        from integrations.messaging.base import ChannelNotSupported

        with patch(
            "apps.authentication.tasks.send_otp.delay",
            side_effect=OSError("broker unreachable"),
        ):
            with self.assertRaises(ChannelNotSupported):
                OTPDeliveryService()._queue_or_send(
                    destination="outage@example.com",
                    code="123456",
                    purpose="LOGIN",
                    channel="SMS",
                )
