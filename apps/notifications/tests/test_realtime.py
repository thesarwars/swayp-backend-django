"""Live in-app notifications over WebSocket (E8-S5).

The socket is a transport for the in-app channel rather than a channel of its
own, so what has to be proven is mostly about *not* diverging: that it carries
the row that was written, that a user who has in-app switched off gets neither,
and that an unauthenticated socket learns nothing.

The consumer tests use channels' own communicator, so the ASGI application,
the origin validator and the token handshake are all exercised rather than
assumed.
"""

from unittest import mock

from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.notifications.realtime import broadcast, group_for
from apps.notifications.services import notify
from apps.vendors.factories import UserFactory

LAYER = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}


def access_token(user):
    return str(RefreshToken.for_user(user).access_token)


#: The ASGI app wraps the router in AllowedHostsOriginValidator, so a socket
#: with no Origin — or a foreign one — is refused before the consumer runs.
#: Tests therefore have to present one, which is the point: that validator is
#: what stops any site a signed-in user visits from opening a socket here.
ORIGIN = b"http://testserver"


def socket(token=None, origin=ORIGIN):
    from config.asgi import application

    url = "/ws/notifications/"

    if token is not None:
        url = f"{url}?token={token}"

    headers = [(b"origin", origin)] if origin else []

    return WebsocketCommunicator(application, url, headers=headers)


@override_settings(REALTIME_ENABLED=True, CHANNEL_LAYERS=LAYER)
class BroadcastTests(TestCase):

    def setUp(self):
        self.user = UserFactory()

    def test_a_notification_broadcasts_the_row_that_was_written(self):
        """One row, one payload — the socket and GET /notifications/ cannot
        disagree because they are showing the same record."""
        with mock.patch(
            "apps.notifications.channels.in_app.broadcast"
        ) as sent, self.captureOnCommitCallbacks(execute=True):
            result = notify(
                self.user, "PAYMENT_FAILED",
                {"reason": "insufficient funds", "reference": "SWP-1"},
            )

        self.assertTrue(sent.called)

        payload = sent.call_args.kwargs["payload"]

        self.assertEqual(payload["id"], str(result.notification.pk))
        self.assertEqual(payload["type"], "PAYMENT_FAILED")
        self.assertFalse(payload["isRead"])

    def test_in_app_switched_off_broadcasts_nothing(self):
        """The preference is honoured once, where it is owned. There is no
        separate websocket switch to fall out of step with it."""
        from apps.notifications.models import NotificationPreference

        NotificationPreference.objects.update_or_create(
            user=self.user, type="PAYMENT_FAILED",
            defaults={"in_app": False},
        )

        with mock.patch(
            "apps.notifications.channels.in_app.broadcast"
        ) as sent, self.captureOnCommitCallbacks(execute=True):
            notify(
                self.user, "PAYMENT_FAILED",
                {"reason": "x", "reference": "SWP-2"},
            )

        self.assertFalse(sent.called)

    def test_the_broadcast_waits_for_commit(self):
        """A browser must never be shown a row that is about to roll back."""
        with mock.patch(
            "apps.notifications.channels.in_app.broadcast"
        ) as sent:
            notify(
                self.user, "PAYMENT_FAILED",
                {"reason": "x", "reference": "SWP-3"},
            )

            # Still inside the test's transaction: nothing has committed.
            self.assertFalse(sent.called)

    @override_settings(REALTIME_ENABLED=False)
    def test_the_flag_off_is_a_no_op_not_an_error(self):
        self.assertFalse(broadcast(user_id="abc", payload={}))

    def test_a_broken_channel_layer_never_raises(self):
        """A payment must not fail because Redis is unreachable."""
        with mock.patch(
            "channels.layers.get_channel_layer",
            side_effect=RuntimeError("redis is down"),
        ):
            self.assertFalse(broadcast(user_id="abc", payload={"a": 1}))

    def test_the_group_name_comes_from_the_primary_key(self):
        """Group names reach Redis, which rejects characters a display name
        would happily contain."""
        self.assertEqual(group_for(self.user.pk), f"notify.user.{self.user.pk}")


@override_settings(
    REALTIME_ENABLED=True, CHANNEL_LAYERS=LAYER, ALLOWED_HOSTS=["testserver"]
)
class SocketHandshakeTests(TransactionTestCase):
    """TransactionTestCase because the consumer talks to the database from a
    separate thread, which cannot see an uncommitted TestCase transaction."""

    async def test_a_valid_token_connects(self):
        user, token = await self.make_user()
        communicator = socket(token)

        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        self.assertEqual(
            (await communicator.receive_json_from())["type"], "connected"
        )

        await communicator.disconnect()

    async def test_no_token_is_refused(self):
        communicator = socket()

        connected, code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_a_garbage_token_is_refused(self):
        communicator = socket("not-a-jwt")

        connected, code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    @override_settings(REALTIME_ENABLED=False)
    async def test_the_flag_off_refuses_rather_than_accepting_silently(self):
        """Accept-and-never-deliver looks like a broken backend."""
        user, token = await self.make_user()
        communicator = socket(token)

        connected, code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4503)

    async def test_a_foreign_origin_is_refused_before_the_token_is_read(self):
        """A WebSocket is not subject to the same-origin policy the way
        fetch() is, so without this any site a signed-in user visits could
        open a socket to this host.

        The validator is built here with an explicit allow-list rather than
        reused from config.asgi: the test settings inherit
        CORS_ALLOW_ALL_ORIGINS=True from base.py, which correctly allows
        everything in development — and the module-level application captures
        its origin list once at import, so override_settings cannot reach it.
        """
        from channels.routing import URLRouter
        from channels.security.websocket import OriginValidator
        from channels.testing import WebsocketCommunicator

        from apps.notifications.routing import websocket_urlpatterns

        guarded = OriginValidator(
            URLRouter(websocket_urlpatterns), ["https://app.getswayp.com"]
        )

        user, token = await self.make_user()
        communicator = WebsocketCommunicator(
            guarded,
            f"/ws/notifications/?token={token}",
            headers=[(b"origin", b"https://evil.example.com")],
        )

        connected, _ = await communicator.connect()

        self.assertFalse(connected)

    async def test_the_configured_frontend_origin_is_accepted(self):
        """The other half: the allow-list must actually let the real frontend
        in, which is what the ALLOWED_HOSTS version got wrong."""
        from channels.routing import URLRouter
        from channels.security.websocket import OriginValidator
        from channels.testing import WebsocketCommunicator

        from apps.notifications.routing import websocket_urlpatterns

        guarded = OriginValidator(
            URLRouter(websocket_urlpatterns), ["https://app.getswayp.com"]
        )

        user, token = await self.make_user()
        communicator = WebsocketCommunicator(
            guarded,
            f"/ws/notifications/?token={token}",
            headers=[(b"origin", b"https://app.getswayp.com")],
        )

        connected, _ = await communicator.connect()

        self.assertTrue(connected)

        await communicator.disconnect()

    async def test_a_deactivated_account_cannot_hold_a_socket(self):
        """A token outlives the account being switched off, so the check has
        to be at connect time, not only at issue time."""
        from channels.db import database_sync_to_async

        def build():
            user = UserFactory(is_active=False)

            return access_token(user)

        communicator = socket(await database_sync_to_async(build)())

        connected, code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_a_connected_socket_receives_its_own_broadcast(self):
        user, token = await self.make_user()
        communicator = socket(token)

        await communicator.connect()
        await communicator.receive_json_from()

        await self.push(user.pk, {"id": "1", "title": "Hello"})

        message = await communicator.receive_json_from()

        self.assertEqual(message["type"], "notification")
        self.assertEqual(message["notification"]["title"], "Hello")

        await communicator.disconnect()

    async def test_one_user_never_receives_anothers_notification(self):
        mine, token = await self.make_user()
        theirs, _ = await self.make_user()

        communicator = socket(token)
        await communicator.connect()
        await communicator.receive_json_from()

        await self.push(theirs.pk, {"id": "2", "title": "Not yours"})

        self.assertTrue(await communicator.receive_nothing(timeout=0.3))

        await communicator.disconnect()

    async def test_ping_is_answered(self):
        user, token = await self.make_user()
        communicator = socket(token)

        await communicator.connect()
        await communicator.receive_json_from()
        await communicator.send_json_to({"type": "ping"})

        self.assertEqual(
            (await communicator.receive_json_from())["type"], "pong"
        )

        await communicator.disconnect()

    async def test_an_unknown_inbound_message_does_not_drop_the_socket(self):
        """A proxy or client library sending something unexpected must not
        take down a working connection."""
        user, token = await self.make_user()
        communicator = socket(token)

        await communicator.connect()
        await communicator.receive_json_from()
        await communicator.send_json_to({"type": "who-knows"})

        await self.push(user.pk, {"id": "3", "title": "Still here"})

        message = await communicator.receive_json_from()

        self.assertEqual(message["notification"]["title"], "Still here")

        await communicator.disconnect()

    # --- helpers ----------------------------------------------------------

    @staticmethod
    async def make_user():
        """Returns (user, access token).

        Both in one database_sync_to_async call: RefreshToken.for_user writes
        an OutstandingToken row, so minting the token is a synchronous
        database call and raises SynchronousOnlyOperation if it happens in the
        async test body.
        """
        from channels.db import database_sync_to_async

        def build():
            # is_active defaults to False on the User model, and the consumer
            # refuses an inactive account — so the factory default would fail
            # every handshake for the wrong reason.
            user = UserFactory(is_active=True)

            return user, access_token(user)

        return await database_sync_to_async(build)()

    @staticmethod
    async def push(user_id, payload):
        from channels.layers import get_channel_layer

        await get_channel_layer().group_send(
            group_for(user_id),
            {"type": "notification.message", "payload": payload},
        )


class OriginPolicyTests(TestCase):
    """Which origins may open a socket.

    This is the one piece of the feature that could pass every test and every
    local check and still refuse every real user: the frontend and the API are
    different hosts, so validating the browser's Origin against ALLOWED_HOSTS
    — which names the API — rejects the frontend in production while working
    perfectly in development.
    """

    def origins(self):
        from config.asgi import websocket_origins

        return websocket_origins()

    @override_settings(
        CORS_ALLOW_ALL_ORIGINS=False,
        CORS_ALLOWED_ORIGINS=["https://app.getswayp.com"],
        ALLOWED_HOSTS=["api.getswayp.com"],
    )
    def test_the_frontend_origin_is_allowed_not_the_api_host(self):
        """The regression this exists for."""
        self.assertEqual(self.origins(), ["https://app.getswayp.com"])
        self.assertNotIn("api.getswayp.com", self.origins())

    @override_settings(
        CORS_ALLOW_ALL_ORIGINS=False,
        CORS_ALLOWED_ORIGINS=["https://app.getswayp.com"],
    )
    def test_it_matches_the_cors_policy_exactly(self):
        """Read from one place, so HTTP and WebSocket cannot drift apart."""
        from django.conf import settings

        self.assertEqual(self.origins(), settings.CORS_ALLOWED_ORIGINS)

    @override_settings(CORS_ALLOW_ALL_ORIGINS=True)
    def test_development_allows_everything(self):
        self.assertEqual(self.origins(), ["*"])

    @override_settings(
        CORS_ALLOW_ALL_ORIGINS=False,
        CORS_ALLOWED_ORIGINS=[],
        ALLOWED_HOSTS=["api.getswayp.com"],
        DEBUG=False,
    )
    def test_with_no_cors_list_it_falls_back_to_the_hosts_we_answer_to(self):
        """Correct for a same-origin deployment, and never empty-and-open."""
        self.assertEqual(self.origins(), ["api.getswayp.com"])


class PushAndSocketAgreeTests(TestCase):
    """The two live paths must be de-duplicable by the client.

    A user with a socket open AND push enabled receives both for one event.
    The frontend is told to dedupe on notificationId, which only works if the
    push payload actually carries the id of the row the socket delivered.
    """

    @override_settings(PUSH_ENABLED=True, REALTIME_ENABLED=True,
                       CHANNEL_LAYERS=LAYER)
    def test_the_push_payload_carries_the_row_the_socket_broadcast(self):
        from apps.notifications.channels.push import PushChannel
        from apps.notifications.models import NotificationPreference

        user = UserFactory()
        NotificationPreference.objects.update_or_create(
            user=user, type="PAYMENT_FAILED", defaults={"push": True},
        )

        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)

        with mock.patch.object(
            PushChannel, "_queue", side_effect=capture
        ), mock.patch(
            "apps.notifications.channels.in_app.broadcast"
        ) as sent, self.captureOnCommitCallbacks(execute=True):
            result = notify(
                user, "PAYMENT_FAILED",
                {"reason": "x", "reference": "SWP-9"},
            )

        row_id = str(result.notification.pk)

        self.assertEqual(sent.call_args.kwargs["payload"]["id"], row_id)
        self.assertEqual(captured["data"]["notificationId"], row_id)

    def test_the_in_app_row_exists_before_push_reads_it(self):
        """PushChannel takes the notification id off the dispatch, which only
        works because InAppChannel is registered ahead of it."""
        from apps.notifications.channels import CHANNELS

        keys = [channel.key for channel in CHANNELS]

        self.assertLess(keys.index("IN_APP"), keys.index("PUSH"))


@override_settings(
    REALTIME_ENABLED=True, CHANNEL_LAYERS=LAYER, ALLOWED_HOSTS=["testserver"]
)
class HeaderAuthTests(TransactionTestCase):
    """DASH-3 / SEC-4: a native app sends its token as a header, so it stays
    out of the URL, and is not refused by the browser-only origin check."""

    make_user = staticmethod(SocketHandshakeTests.make_user)

    def guarded(self, headers, url="/ws/notifications/"):
        """The production validator with a real allow-list. Built here because
        config.asgi captures its list at import (see the origin tests)."""
        from channels.routing import URLRouter

        from apps.notifications.routing import websocket_urlpatterns
        from apps.notifications.ws_origin import BrowserOriginValidator

        app = BrowserOriginValidator(
            URLRouter(websocket_urlpatterns), ["https://app.getswayp.com"]
        )

        return WebsocketCommunicator(app, url, headers=headers)

    async def test_a_bearer_header_connects_with_no_origin(self):
        _, token = await self.make_user()
        communicator = self.guarded(
            [(b"authorization", f"Bearer {token}".encode())]
        )

        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_a_bearer_header_connects_with_the_api_host_as_origin(self):
        """What React Native sends as Origin: the URL it is connecting to."""
        _, token = await self.make_user()
        communicator = self.guarded(
            [
                (b"origin", b"https://api.getswayp.com"),
                (b"authorization", f"Bearer {token}".encode()),
            ]
        )

        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_a_bad_header_token_is_still_refused(self):
        communicator = self.guarded([(b"authorization", b"Bearer not-a-jwt")])

        connected, code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_a_non_bearer_header_does_not_fall_back_to_the_query(self):
        _, token = await self.make_user()
        communicator = self.guarded(
            [(b"authorization", b"Basic abc")],
            url=f"/ws/notifications/?token={token}",
        )

        connected, code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_a_query_token_with_no_origin_is_still_refused(self):
        """The browser path keeps its origin check: no header, no exemption."""
        _, token = await self.make_user()
        communicator = self.guarded([], url=f"/ws/notifications/?token={token}")

        connected, _ = await communicator.connect()

        self.assertFalse(connected)
