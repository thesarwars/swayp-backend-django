"""Plaid's HISTORICAL_UPDATE is what wakes a waiting scan.

The scan started at connect time stops with BankDataNotReady and stays
RUNNING, because Plaid pulls history asynchronously. Without this callback it
waits forever, or — worse — a retry succeeds against a partially-filled item
and detection runs over one month of data instead of two years, reporting a
near-empty result that looks like an answer.

Signed with the mock provider's HMAC. The real scheme is an ES256 JWT and is
covered in the provider's own tests; what matters here is that an unverified
callback never reaches the handler.
"""

import hashlib
import hmac
import json
from unittest import mock

from django.test import TestCase, override_settings

from apps.banking.factories import (
    BankConnectionFactory,
    TransactionScanFactory,
)
from apps.banking.models import TransactionScan
from apps.banking.services.plaid_webhook_service import (
    RESULT_IGNORED,
    RESULT_RESUMED,
    RESULT_STARTED,
    RESULT_UNKNOWN_ITEM,
    PlaidWebhookService,
)
from apps.common.enums import ScanStatus
from apps.payments.models import WebhookEvent

URL = "/webhooks/plaid"
SECRET = "plaid-test-webhook-secret"


@override_settings(
    WEBHOOK_SECRETS={"PLAID": SECRET}, BANK_DATA_PROVIDER="mock"
)
class PlaidWebhookEndpointTests(TestCase):

    def setUp(self):
        self.connection = BankConnectionFactory(item_id="item-abc")
        self.scan = TransactionScanFactory(
            connection=self.connection, status=ScanStatus.RUNNING
        )

    def post(self, payload, signature=None):
        body = json.dumps(payload)

        if signature is None:
            signature = hmac.new(
                SECRET.encode(), body.encode(), hashlib.sha256
            ).hexdigest()

        return self.client.post(
            URL,
            data=body,
            content_type="application/json",
            HTTP_PLAID_VERIFICATION=signature,
        )

    def ready_payload(self, **overrides):
        payload = {
            "webhook_type": "TRANSACTIONS",
            "webhook_code": "HISTORICAL_UPDATE",
            "item_id": "item-abc",
            "new_transactions": 412,
        }
        payload.update(overrides)

        return payload

    # -- the signature gate -------------------------------------------------

    def test_an_unsigned_callback_is_refused(self):
        response = self.post(self.ready_payload(), signature="")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(WebhookEvent.objects.exists())

    def test_a_forged_signature_is_refused(self):
        response = self.post(self.ready_payload(), signature="deadbeef")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(WebhookEvent.objects.exists())

    # -- the id Plaid does not send -----------------------------------------

    def test_a_callback_with_no_id_field_is_still_accepted(self):
        """The shared "payload has no event id" check rejected every one."""
        with mock.patch(
            "apps.banking.tasks.sync_transactions.delay"
        ) as queued:
            # The task is queued on commit — deliberately, so a scan is never
            # handed a row that a rollback is about to remove. TestCase wraps
            # each test in a transaction that never commits, so without this
            # the callback simply never runs.
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post(self.ready_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["result"], RESULT_RESUMED)
        queued.assert_called_once()

    def test_a_repeat_delivery_is_a_duplicate(self):
        """Plaid retries the same bytes until it gets a 200."""
        with mock.patch(
            "apps.banking.tasks.sync_transactions.delay"
        ) as queued:
            with self.captureOnCommitCallbacks(execute=True):
                self.post(self.ready_payload())

            with self.captureOnCommitCallbacks(execute=True):
                second = self.post(self.ready_payload())

        self.assertEqual(second.data["result"], "duplicate")
        self.assertEqual(queued.call_count, 1)
        self.assertEqual(WebhookEvent.objects.count(), 1)

    def test_the_event_is_recorded_for_audit(self):
        with mock.patch("apps.banking.tasks.sync_transactions.delay"):
            self.post(self.ready_payload())

        event = WebhookEvent.objects.get()

        self.assertEqual(event.processor, "PLAID")
        self.assertEqual(event.event_type, "HISTORICAL_UPDATE")
        self.assertIn("item-abc", event.event_id)


class PlaidWebhookServiceTests(TestCase):

    def setUp(self):
        self.connection = BankConnectionFactory(item_id="item-abc")

    def handle(self, **overrides):
        payload = {
            "webhook_type": "TRANSACTIONS",
            "webhook_code": "HISTORICAL_UPDATE",
            "item_id": "item-abc",
        }
        payload.update(overrides)

        with mock.patch(
            "apps.banking.tasks.sync_transactions.delay"
        ) as queued:
            with self.captureOnCommitCallbacks(execute=True):
                result = PlaidWebhookService().handle(payload)

        return result, queued

    def test_a_waiting_scan_is_resumed_rather_than_duplicated(self):
        scan = TransactionScanFactory(
            connection=self.connection, status=ScanStatus.RUNNING
        )

        result, queued = self.handle()

        self.assertEqual(result, RESULT_RESUMED)
        self.assertEqual(TransactionScan.objects.count(), 1)
        queued.assert_called_once_with(scan_id=str(scan.id))

    def test_a_scan_is_started_when_none_is_waiting(self):
        """The history is ready and nobody asked. Better than dropping it."""
        result, queued = self.handle()

        self.assertEqual(result, RESULT_STARTED)
        self.assertEqual(TransactionScan.objects.count(), 1)
        queued.assert_called_once()

    def test_a_finished_scan_is_not_resumed(self):
        TransactionScanFactory(
            connection=self.connection, status=ScanStatus.DONE
        )

        result, _ = self.handle()

        self.assertEqual(result, RESULT_STARTED)

    def test_initial_update_is_ignored(self):
        """It carries 30 days. Scanning on it is the bug, not the fix."""
        result, queued = self.handle(webhook_code="INITIAL_UPDATE")

        self.assertEqual(result, RESULT_IGNORED)
        queued.assert_not_called()

    def test_an_unknown_item_is_acknowledged_not_retried(self):
        """A removed item keeps emitting for a while."""
        result, queued = self.handle(item_id="item-gone")

        self.assertEqual(result, RESULT_UNKNOWN_ITEM)
        queued.assert_not_called()

    def test_an_unrecognised_code_does_not_raise(self):
        result, queued = self.handle(webhook_code="SOMETHING_NEW")

        self.assertEqual(result, RESULT_IGNORED)
        queued.assert_not_called()
