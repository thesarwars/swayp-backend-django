"""E8-S3 — notify(), the one way an event becomes a notification.

The matrix test is the AC. The rest pin the properties that make the matrix
trustworthy: SMS and push are unreachable rather than disabled, email is off
behind a flag and cannot raise into the caller whatever happens to the broker,
and a copy bug is a red test rather than a half-rendered sentence.
"""

from unittest import mock

from django.conf import settings
from django.db import transaction
from django.test import TestCase, override_settings

from apps.common.enums import NotificationType
from apps.notifications.channels import (
    CHANNELS,
    DISABLED,
    FAILED,
    PENDING_COMMIT,
    SENT,
    SKIPPED_BY_PREFERENCE,
    SUPPORTED_KEYS,
    UNSUPPORTED,
    EmailChannel,
    InAppChannel,
)
from apps.notifications.channels.base import FIELD_TO_KEY
from apps.notifications.models import (
    CHANNEL_FIELDS,
    Notification,
    NotificationPreference,
)
from apps.notifications.services import notify
from apps.notifications.services.dispatch_service import dedupe_key_is_storable
from apps.vendors.factories import UserFactory
from integrations.messaging.base import DeliveryResult

BILL_DUE_CONTEXT = {
    "vendor_name": "WeWork",
    "amount": "3200.00",
    "due_date": "2026-08-01",
    "bill_id": "b1",
    "occurrence_id": "o1",
}

_PROVIDER = "apps.notifications.tasks.get_messaging_provider"
_DELAY = "apps.notifications.channels.email.send_notification_email.delay"
_STORABLE = (
    "apps.notifications.services.dispatch_service.dedupe_key_is_storable"
)


class SpyMessagingProvider:
    """Records every send instead of delivering one."""

    name = "spy"

    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)

        return DeliveryResult(delivered=True, provider_reference="SPY-1")


class ChannelRegistryTests(TestCase):

    def test_in_app_is_dispatched_before_any_external_channel(self):
        """Not stylistic ordering.

        The in-app write is the durable record and, from E8-S4, the row that
        claims the dedupe key — so it has to resolve before an email is
        queued for an event a key collision is about to reject.
        """
        self.assertEqual(len(CHANNELS), 2)
        self.assertIsInstance(CHANNELS[0], InAppChannel)
        self.assertIsInstance(CHANNELS[1], EmailChannel)

    def test_every_preference_column_has_a_channel_key(self):
        self.assertEqual(tuple(FIELD_TO_KEY), CHANNEL_FIELDS)

    def test_external_delivery_is_off_by_default(self):
        """The guard-rail every other argument in this story rests on.

        With email off, a user who switches in_app off receives nothing at
        all — which is what makes "no in-app row means no dedupe key" safe
        until the NotificationDispatch ledger lands.
        """
        self.assertFalse(settings.NOTIFICATION_EMAIL_ENABLED)


class NotifyTests(TestCase):

    def setUp(self):
        self.user = UserFactory()

    def test_notify_uses_column_defaults_when_no_row_exists(self):
        result = notify(
            self.user, NotificationType.BILL_DUE, BILL_DUE_CONTEXT
        )

        notification = Notification.objects.get()
        self.assertEqual(notification.type, NotificationType.BILL_DUE)
        self.assertEqual(notification.metadata, BILL_DUE_CONTEXT)
        self.assertEqual(notification.title, "WeWork is due")
        self.assertEqual(
            notification.message,
            "WeWork for 3200.00 was due on 2026-08-01. Approve it to pay.",
        )
        self.assertEqual(result.notification, notification)

        # Reading a preference must never materialise one.
        self.assertEqual(NotificationPreference.objects.count(), 0)

    @override_settings(NOTIFICATION_EMAIL_ENABLED=True)
    def test_notify_channel_matrix(self):
        expected_in_app = {True: SENT, False: SKIPPED_BY_PREFERENCE}
        expected_email = {
            True: PENDING_COMMIT,
            False: SKIPPED_BY_PREFERENCE,
        }

        for in_app in (True, False):
            for email in (True, False):
                with self.subTest(in_app=in_app, email=email):
                    Notification.objects.all().delete()
                    NotificationPreference.objects.update_or_create(
                        user=self.user,
                        type=NotificationType.BILL_DUE,
                        defaults={"in_app": in_app, "email": email},
                    )

                    provider = SpyMessagingProvider()

                    with mock.patch(_PROVIDER, return_value=provider):
                        with self.captureOnCommitCallbacks(execute=True):
                            result = notify(
                                self.user,
                                NotificationType.BILL_DUE,
                                BILL_DUE_CONTEXT,
                            )

                    self.assertEqual(
                        Notification.objects.count(), 1 if in_app else 0
                    )
                    self.assertEqual(
                        len(provider.messages), 1 if email else 0
                    )
                    self.assertEqual(
                        result.outcomes,
                        {
                            "IN_APP": expected_in_app[in_app],
                            "EMAIL": expected_email[email],
                            "SMS": UNSUPPORTED,
                            "PUSH": UNSUPPORTED,
                        },
                    )

    @override_settings(NOTIFICATION_EMAIL_ENABLED=True)
    def test_notify_never_reports_sms_or_push_as_sent(self):
        # Forced on at the ORM level, bypassing the API that refuses them.
        NotificationPreference.objects.create(
            user=self.user,
            type=NotificationType.BILL_DUE,
            sms=True,
            push=True,
        )

        provider = SpyMessagingProvider()

        with mock.patch(_PROVIDER, return_value=provider):
            with self.captureOnCommitCallbacks(execute=True):
                result = notify(
                    self.user, NotificationType.BILL_DUE, BILL_DUE_CONTEXT
                )

        self.assertEqual(result.outcomes["SMS"], UNSUPPORTED)
        self.assertEqual(result.outcomes["PUSH"], UNSUPPORTED)
        self.assertEqual(
            {message.channel for message in provider.messages}, {"EMAIL"}
        )
        # Structural, not conditional: there is no SmsChannel to reach.
        self.assertEqual(SUPPORTED_KEYS, {"IN_APP", "EMAIL"})

    def test_email_is_not_attempted_while_the_flag_is_off(self):
        provider = SpyMessagingProvider()

        with mock.patch(_PROVIDER, return_value=provider):
            with self.captureOnCommitCallbacks(execute=True):
                result = notify(
                    self.user, NotificationType.BILL_DUE, BILL_DUE_CONTEXT
                )

        self.assertEqual(result.outcomes["EMAIL"], DISABLED)
        self.assertEqual(provider.messages, [])
        self.assertEqual(Notification.objects.count(), 1)

    @override_settings(NOTIFICATION_EMAIL_ENABLED=True)
    def test_email_failure_never_reaches_the_caller(self):
        """Two ways delivery can break, neither of which is the caller's."""
        with mock.patch(
            _PROVIDER, side_effect=RuntimeError("mail server is down")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                result = notify(
                    self.user, NotificationType.BILL_DUE, BILL_DUE_CONTEXT
                )

        self.assertEqual(result.outcomes["IN_APP"], SENT)
        self.assertEqual(result.outcomes["EMAIL"], PENDING_COMMIT)
        self.assertEqual(Notification.objects.count(), 1)

        dead_broker = mock.Mock(side_effect=OSError("broker unreachable"))

        with mock.patch(_DELAY, dead_broker):
            with self.assertLogs(
                "apps.notifications.channels.email", level="ERROR"
            ) as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    broker_result = notify(
                        self.user, NotificationType.BILL_DUE, BILL_DUE_CONTEXT
                    )

        dead_broker.assert_called_once()
        self.assertEqual(Notification.objects.count(), 2)
        # The enqueue is attempted after the caller's transaction commits, so
        # deliver() cannot know it failed. It says PENDING_COMMIT — never
        # "queued", which would claim the broker took it — and the failure is
        # recorded where it can actually be seen.
        self.assertEqual(broker_result.outcomes["EMAIL"], PENDING_COMMIT)
        self.assertIn(
            "could not queue notification email", "\n".join(logs.output)
        )

    @override_settings(NOTIFICATION_EMAIL_ENABLED=True)
    def test_a_user_with_no_address_is_reported_as_failed_not_pending(self):
        """The one email outcome that is knowable inside deliver().

        FAILED means it provably did not go out, decided before the method
        returned; PENDING_COMMIT means nobody can know yet. Keeping the two
        apart is what stops PENDING_COMMIT from quietly becoming a synonym
        for "something happened".
        """
        addressless = UserFactory(email="")
        delay = mock.Mock()

        with mock.patch(_DELAY, delay):
            with self.captureOnCommitCallbacks(execute=True):
                result = notify(
                    addressless, NotificationType.BILL_DUE, BILL_DUE_CONTEXT
                )

        self.assertEqual(result.outcomes["EMAIL"], FAILED)
        delay.assert_not_called()
        # The durable in-app record is written either way.
        self.assertEqual(result.outcomes["IN_APP"], SENT)

    @override_settings(NOTIFICATION_EMAIL_ENABLED=True)
    def test_no_email_is_queued_when_the_callers_transaction_rolls_back(self):
        """What PENDING_COMMIT buys, asserted rather than assumed.

        A payment that rolls back must not leave a user holding an email
        about it.
        """
        provider = SpyMessagingProvider()
        delay = mock.Mock()

        with mock.patch(_PROVIDER, return_value=provider):
            with mock.patch(_DELAY, delay):
                with self.captureOnCommitCallbacks(
                    execute=True
                ) as callbacks:
                    with self.assertRaises(RuntimeError):
                        with transaction.atomic():
                            notify(
                                self.user,
                                NotificationType.BILL_DUE,
                                BILL_DUE_CONTEXT,
                            )
                            raise RuntimeError("the caller blew up")

        self.assertEqual(callbacks, [])
        delay.assert_not_called()
        self.assertEqual(provider.messages, [])
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_raises_on_a_missing_template_key(self):
        with self.assertRaises(ValueError):
            notify(
                self.user,
                NotificationType.BILL_DUE,
                {"vendor_name": "WeWork"},
            )

        with self.assertRaises(ValueError):
            notify(
                self.user,
                NotificationType.BILL_DUE,
                BILL_DUE_CONTEXT,
                title="My own title",
                message="My own message",
            )

        with self.assertRaises(ValueError):
            notify(self.user, NotificationType.SYSTEM, {})

        with self.assertRaises(ValueError):
            notify(self.user, "WIDGET", {})

        self.assertEqual(Notification.objects.count(), 0)

    def test_an_untemplated_type_carries_the_call_sites_own_copy(self):
        notify(
            self.user,
            NotificationType.SYSTEM,
            {"bill_id": "b1"},
            title="Autopay needs your attention",
            message="Re-enable autopay to continue.",
        )

        notification = Notification.objects.get()
        self.assertEqual(notification.type, NotificationType.SYSTEM)
        self.assertEqual(notification.title, "Autopay needs your attention")
        self.assertEqual(notification.metadata, {"bill_id": "b1"})

    def test_a_dedupe_key_reaches_the_row_the_in_app_channel_writes(self):
        """E8-S4 added Notification.dedupe_key, so the guard disarmed itself.

        The other half is the known hole this whole story's email default
        rests on: the key rides on the in-app row, so a user with in_app off
        has no row and no key. E8-S4 pins the consequence; this pins the
        mechanism.
        """
        self.assertTrue(dedupe_key_is_storable())

        result = notify(
            self.user,
            NotificationType.BILL_DUE,
            BILL_DUE_CONTEXT,
            dedupe_key="BILL_DUE:o1:2026-08-01",
        )

        self.assertEqual(
            result.notification.dedupe_key, "BILL_DUE:o1:2026-08-01"
        )
        self.assertEqual(
            Notification.objects.get().dedupe_key, "BILL_DUE:o1:2026-08-01"
        )

        NotificationPreference.objects.create(
            user=self.user,
            type=NotificationType.BILL_DUE,
            in_app=False,
            email=True,
        )

        skipped = notify(
            self.user,
            NotificationType.BILL_DUE,
            BILL_DUE_CONTEXT,
            dedupe_key="BILL_DUE:o1:2026-08-02",
        )

        self.assertIsNone(skipped.notification)
        self.assertEqual(Notification.objects.count(), 1)

    @override_settings(NOTIFICATION_EMAIL_ENABLED=True)
    def test_a_dedupe_key_is_never_silently_dropped(self):
        """A key that cannot be persisted is a TypeError, not a shrug.

        The refusal is made in notify() before any channel runs, and
        critically it cannot depend on the user's preferences: the in-app
        write is what stores the key, and that channel is skipped outright
        for a user with in_app off. Reached here by pretending the column is
        gone, which is the only way back into this branch now that E8-S4 has
        shipped it.
        """
        for in_app in (True, False):
            with self.subTest(in_app=in_app):
                Notification.objects.all().delete()
                NotificationPreference.objects.update_or_create(
                    user=self.user,
                    type=NotificationType.BILL_DUE,
                    defaults={"in_app": in_app, "email": True},
                )

                provider = SpyMessagingProvider()

                with mock.patch(_STORABLE, return_value=False):
                    with mock.patch(_PROVIDER, return_value=provider):
                        with self.captureOnCommitCallbacks(execute=True):
                            with self.assertRaises(TypeError):
                                notify(
                                    self.user,
                                    NotificationType.BILL_DUE,
                                    BILL_DUE_CONTEXT,
                                    dedupe_key="BILL_DUE:o1:2026-08-01",
                                )

                # Refused before anything was written or handed off, so the
                # caller cannot mistake a dropped key for a deduplicated one.
                self.assertEqual(Notification.objects.count(), 0)
                self.assertEqual(provider.messages, [])

        NotificationPreference.objects.all().delete()

        with mock.patch(_STORABLE, return_value=False):
            result = notify(
                self.user,
                NotificationType.BILL_DUE,
                BILL_DUE_CONTEXT,
                dedupe_key=None,
            )

        self.assertIsNotNone(result.notification)
