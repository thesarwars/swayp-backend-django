"""Push delivery (E8-S5).

PUSH was a reserved channel key with no adapter since E8-S3 — declared, and
refused on the preferences endpoint, so the vocabulary existed while nothing
could ever be delivered. These drive the API rather than the service, because
the failure this feature is most likely to have is not wrong logic: it is a
channel that is registered but never reached.
"""

from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.notifications.channels import BY_FIELD, CHANNELS, PUSH
from apps.notifications.models import DeviceToken
from apps.notifications.services import notify
from apps.notifications.services.device_service import DeviceService
from apps.vendors.factories import UserFactory

REGISTER = "/api/v1/notifications/devices/register/"
UNREGISTER = "/api/v1/notifications/devices/unregister/"


def auth(user):
    client = APIClient()
    client.force_authenticate(user=user)

    return client


class DeviceRegistrationTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = auth(self.user)

    def test_a_device_registers(self):
        response = self.client.post(
            REGISTER,
            {"token": "tok-1", "platform": "IOS", "deviceName": "iPhone"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            DeviceToken.objects.filter(user=self.user, token="tok-1")
        )

    def test_the_token_is_never_echoed_back(self):
        """It is a bearer string; a response body is the wrong place for it."""
        response = self.client.post(
            REGISTER, {"token": "tok-secret", "platform": "WEB"},
            format="json",
        )

        self.assertNotIn("tok-secret", str(response.data))

    def test_registering_twice_does_not_duplicate(self):
        """Clients re-register on every launch — FCM rotates tokens."""
        for _ in range(3):
            self.client.post(
                REGISTER, {"token": "tok-1", "platform": "IOS"},
                format="json",
            )

        self.assertEqual(DeviceToken.objects.filter(token="tok-1").count(), 1)

    def test_a_token_moves_to_whoever_signed_in_last(self):
        """A shared device must not keep notifying the previous account."""
        first = self.user
        second = UserFactory()

        auth(first).post(
            REGISTER, {"token": "shared", "platform": "ANDROID"},
            format="json",
        )
        auth(second).post(
            REGISTER, {"token": "shared", "platform": "ANDROID"},
            format="json",
        )

        rows = DeviceToken.objects.filter(token="shared")

        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().user_id, second.pk)

    def test_a_whitespace_only_token_is_refused(self):
        response = self.client.post(
            REGISTER, {"token": "   ", "platform": "WEB"}, format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_trailing_newline_is_stripped_rather_than_stored(self):
        """Otherwise the row looks healthy and never receives anything."""
        self.client.post(
            REGISTER, {"token": "tok-2\n", "platform": "WEB"}, format="json",
        )

        self.assertTrue(DeviceToken.objects.filter(token="tok-2"))

    def test_an_unknown_platform_is_refused(self):
        response = self.client.post(
            REGISTER, {"token": "t", "platform": "BLACKBERRY"}, format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_registration_requires_authentication(self):
        response = APIClient().post(
            REGISTER, {"token": "t", "platform": "WEB"}, format="json",
        )

        self.assertIn(response.status_code, (401, 403))


class UnregisterTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = auth(self.user)
        self.client.post(
            REGISTER, {"token": "mine", "platform": "IOS"}, format="json",
        )

    def test_unregister_deactivates(self):
        self.client.post(UNREGISTER, {"token": "mine"}, format="json")

        self.assertFalse(DeviceToken.objects.get(token="mine").is_active)

    def test_it_is_idempotent(self):
        self.client.post(UNREGISTER, {"token": "mine"}, format="json")
        response = self.client.post(
            UNREGISTER, {"token": "mine"}, format="json"
        )

        self.assertEqual(response.status_code, 200)

    def test_an_unknown_token_still_answers_200(self):
        """Whether a token exists is not something this may reveal."""
        response = self.client.post(
            UNREGISTER, {"token": "never-seen"}, format="json"
        )

        self.assertEqual(response.status_code, 200)

    def test_one_user_cannot_silence_anothers_device(self):
        """The token is a bearer string, so the write must be user-scoped."""
        attacker = auth(UserFactory())

        attacker.post(UNREGISTER, {"token": "mine"}, format="json")

        self.assertTrue(DeviceToken.objects.get(token="mine").is_active)

    def test_registering_again_revives_a_dead_row(self):
        """A reinstall proves the device is alive again."""
        DeviceService().deactivate_tokens(tokens=("mine",))

        self.client.post(
            REGISTER, {"token": "mine", "platform": "IOS"}, format="json"
        )

        self.assertTrue(DeviceToken.objects.get(token="mine").is_active)


class ChannelRegistrationTests(TestCase):

    def test_push_now_has_an_adapter(self):
        """The whole act of enabling a channel is registering its class."""
        self.assertIn("push", BY_FIELD)
        self.assertIn(PUSH, {channel.key for channel in CHANNELS})

    def test_the_in_app_channel_still_runs_first(self):
        """It writes the durable row and claims the dedupe key, so it has to
        resolve before any external channel is dispatched."""
        self.assertEqual(CHANNELS[0].key, "IN_APP")

    def test_sms_still_has_no_adapter(self):
        """Registering push must not have enabled anything else."""
        self.assertNotIn("sms", BY_FIELD)


@override_settings(PUSH_ENABLED=True, NOTIFICATION_EMAIL_ENABLED=False)
class PushDeliveryTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        DeviceToken.objects.create(
            user=self.user, token="tok-live", platform="IOS"
        )

    def enable_push_preference(self):
        from apps.notifications.models import NotificationPreference

        NotificationPreference.objects.update_or_create(
            user=self.user, type="PAYMENT_FAILED", defaults={"push": True},
        )

    def test_a_notification_queues_a_push(self):
        self.enable_push_preference()

        with mock.patch(
            "apps.notifications.channels.push.send_push"
        ) as queued, self.captureOnCommitCallbacks(execute=True):
            notify(
                self.user, "PAYMENT_FAILED",
                {"reason": "insufficient funds", "reference": "SWP-1"},
            )

        self.assertTrue(queued.delay.called)

    def test_push_off_in_preferences_sends_nothing(self):
        with mock.patch(
            "apps.notifications.channels.push.send_push"
        ) as queued, self.captureOnCommitCallbacks(execute=True):
            notify(
                self.user, "PAYMENT_FAILED",
                {"reason": "insufficient funds", "reference": "SWP-1"},
            )

        self.assertFalse(queued.delay.called)

    @override_settings(PUSH_ENABLED=False)
    def test_the_kill_switch_stops_delivery(self):
        self.enable_push_preference()

        with mock.patch(
            "apps.notifications.channels.push.send_push"
        ) as queued, self.captureOnCommitCallbacks(execute=True):
            notify(
                self.user, "PAYMENT_FAILED",
                {"reason": "insufficient funds", "reference": "SWP-1"},
            )

        self.assertFalse(queued.delay.called)

    def test_the_payload_carries_no_money_or_vendor_name(self):
        """A push payload is visible to the OS and travels through Apple's
        and Google's infrastructure, so it carries identifiers only."""
        from apps.notifications.channels.push import PushChannel
        from apps.notifications.channels.base import Dispatch

        dispatch = Dispatch(
            user=self.user,
            type="PAYMENT_FAILED",
            title="Payment failed",
            message="Your payment to Acme for $4,200.00 failed.",
            context={"vendorName": "Acme", "amount": "4200.00",
                     "paymentId": "abc"},
        )

        payload = PushChannel._payload(dispatch)

        self.assertEqual(payload["paymentId"], "abc")
        self.assertNotIn("amount", payload)
        self.assertNotIn("vendorName", payload)


class PushTaskTests(TestCase):
    """The task, which is where dead tokens are actually reaped."""

    def setUp(self):
        self.user = UserFactory()

    def send(self):
        from apps.notifications.tasks import send_push

        return send_push(
            user_id=str(self.user.pk), title="t", body="b",
            notification_type="TEST",
        )

    @override_settings(PUSH_ENABLED=True, PUSH_PROVIDER="mock")
    def test_a_dead_token_is_deactivated(self):
        """Otherwise the table fills with tokens retried on every send."""
        DeviceToken.objects.create(
            user=self.user, token="tok-dead", platform="IOS"
        )

        self.send()

        self.assertFalse(DeviceToken.objects.get(token="tok-dead").is_active)

    @override_settings(PUSH_ENABLED=True, PUSH_PROVIDER="mock")
    def test_a_transient_failure_does_not_deactivate(self):
        """A Firebase incident must not unsubscribe every device."""
        DeviceToken.objects.create(
            user=self.user, token="tok-fail", platform="IOS"
        )

        self.send()

        self.assertTrue(DeviceToken.objects.get(token="tok-fail").is_active)

    @override_settings(PUSH_ENABLED=True, PUSH_PROVIDER="mock")
    def test_a_healthy_token_survives_and_reports_sent(self):
        DeviceToken.objects.create(
            user=self.user, token="tok-ok", platform="ANDROID"
        )

        self.assertEqual(self.send(), "sent")
        self.assertTrue(DeviceToken.objects.get(token="tok-ok").is_active)

    @override_settings(PUSH_ENABLED=True, PUSH_PROVIDER="mock")
    def test_a_user_with_no_devices_is_not_an_error(self):
        self.assertEqual(self.send(), "no_devices")

    @override_settings(PUSH_ENABLED=True, PUSH_PROVIDER="mock")
    def test_an_inactive_device_is_not_sent_to(self):
        DeviceToken.objects.create(
            user=self.user, token="tok-off", platform="IOS", is_active=False
        )

        self.assertEqual(self.send(), "no_devices")

    @override_settings(PUSH_ENABLED=False)
    def test_a_queued_task_respects_the_flag_being_turned_off(self):
        """Re-checked in the task, not only in the channel: a task already on
        the queue when the switch flips must not send."""
        DeviceToken.objects.create(
            user=self.user, token="tok-ok", platform="IOS"
        )

        self.assertEqual(self.send(), "disabled")


class PreferenceEndpointTests(TestCase):
    """The preferences endpoint refused push until an adapter existed."""

    def setUp(self):
        self.client = auth(UserFactory())

    def test_push_can_now_be_switched_on(self):
        response = self.client.patch(
            "/api/v1/notifications/preferences/",
            {"preferences": [{"type": "PAYMENT_FAILED", "push": True}]},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_sms_is_still_refused(self):
        """The guard reads the registry, so enabling push must not have
        enabled a channel that still has no adapter."""
        response = self.client.patch(
            "/api/v1/notifications/preferences/",
            {"preferences": [{"type": "PAYMENT_FAILED", "sms": True}]},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
