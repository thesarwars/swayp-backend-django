"""SEC-4: browsers open the socket with a single-use ticket, so no access
token is ever written into a URL."""

from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.notifications.services.ws_ticket_service import (
    WebSocketTicketService,
)
from apps.notifications.tests.test_realtime import LAYER, ORIGIN
from apps.vendors.factories import UserFactory


class TicketServiceTests(TestCase):

    def test_a_ticket_redeems_once(self):
        user = UserFactory()
        ticket = WebSocketTicketService().issue(user)["ticket"]

        self.assertEqual(WebSocketTicketService().redeem(ticket), str(user.pk))
        self.assertIsNone(WebSocketTicketService().redeem(ticket))

    def test_garbage_is_nobody(self):
        self.assertIsNone(WebSocketTicketService().redeem("nope"))
        self.assertIsNone(WebSocketTicketService().redeem(""))

    def test_the_endpoint_needs_a_session_and_answers_a_ticket(self):
        client = APIClient()
        self.assertEqual(
            client.post("/api/v1/notifications/ws-ticket").status_code, 401
        )

        client.force_authenticate(user=UserFactory())
        data = client.post("/api/v1/notifications/ws-ticket").json()["data"]

        self.assertTrue(data["ticket"])
        self.assertEqual(data["expires_in"], 60)


@override_settings(
    REALTIME_ENABLED=True, CHANNEL_LAYERS=LAYER, ALLOWED_HOSTS=["testserver"]
)
class TicketHandshakeTests(TransactionTestCase):

    @staticmethod
    async def ticket_for_new_user():
        from channels.db import database_sync_to_async

        def build():
            user = UserFactory(is_active=True)
            return WebSocketTicketService().issue(user)["ticket"]

        return await database_sync_to_async(build)()

    @staticmethod
    def socket(ticket):
        from channels.testing import WebsocketCommunicator

        from config.asgi import application

        return WebsocketCommunicator(
            application, f"/ws/notifications/?ticket={ticket}",
            headers=[(b"origin", ORIGIN)],
        )

    async def test_a_ticket_opens_one_socket(self):
        ticket = await self.ticket_for_new_user()

        first = self.socket(ticket)
        connected, _ = await first.connect()
        self.assertTrue(connected)
        self.assertEqual((await first.receive_json_from())["type"], "connected")
        await first.disconnect()

        second = self.socket(ticket)
        connected, code = await second.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4401)

    async def test_an_unknown_ticket_is_refused(self):
        communicator = self.socket("made-up")

        connected, code = await communicator.connect()

        self.assertFalse(connected)
        self.assertEqual(code, 4401)
