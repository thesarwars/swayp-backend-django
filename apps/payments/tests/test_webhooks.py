"""Processor webhooks: dedupe, ordering, signatures, late return (E6-S8)."""

import hashlib
import hmac
import json

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.bills.factories import BillFactory, BillOccurrenceFactory
from apps.bills.models.bill_occurrence import BillOccurrence
from apps.common.enums import BillOccurrenceStatus, PaymentStatus
from apps.payments.factories import PaymentFactory
from apps.payments.models import WebhookEvent
from apps.payments.services.webhook_service import (
    RESULT_APPLIED,
    RESULT_DUPLICATE,
    RESULT_IGNORED,
    RESULT_UNKNOWN_PAYMENT,
    SignatureError,
    WebhookService,
    verify_signature,
)
from apps.vendors.factories import UserFactory

SECRET = "mock-webhook-secret"


def sign(body, secret=SECRET):
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class SignatureTests(TestCase):

    def test_a_valid_signature_passes(self):
        body = b'{"id":"evt_1"}'

        self.assertTrue(
            verify_signature(
                processor="MOCK", raw_body=body,
                signature=sign(body), secret=SECRET,
            )
        )

    def test_a_tampered_body_fails(self):
        body = b'{"id":"evt_1"}'
        signature = sign(body)

        with self.assertRaises(SignatureError):
            verify_signature(
                processor="MOCK", raw_body=b'{"id":"evt_2"}',
                signature=signature, secret=SECRET,
            )

    def test_a_missing_signature_fails(self):
        with self.assertRaises(SignatureError):
            verify_signature(
                processor="MOCK", raw_body=b"{}", signature="",
                secret=SECRET,
            )

    def test_an_unconfigured_secret_refuses_rather_than_trusts(self):
        with self.assertRaises(SignatureError):
            verify_signature(
                processor="MOCK", raw_body=b"{}", signature="anything",
                secret="",
            )


class WebhookServiceTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.bill = BillFactory(user=self.user)
        self.occurrence = BillOccurrenceFactory(
            bill=self.bill, status=BillOccurrenceStatus.SCHEDULED
        )
        self.payment = PaymentFactory(
            user=self.user,
            vendor=self.bill.vendor,
            bill_occurrence=self.occurrence,
            status=PaymentStatus.PROCESSING,
        )
        self.service = WebhookService()

    def send(self, event_type, event_id="evt_1", **payload):
        body = {
            "reference": self.payment.transaction_reference,
            **payload,
        }

        return self.service.handle(
            processor="MOCK",
            event_id=event_id,
            event_type=event_type,
            payload=body,
        )

    def test_a_completion_settles_the_payment_and_the_bill(self):
        result = self.send("transfer.completed")

        self.payment.refresh_from_db()
        self.occurrence.refresh_from_db()

        self.assertEqual(result, RESULT_APPLIED)
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESSFUL)
        self.assertEqual(self.occurrence.status, BillOccurrenceStatus.PAID)

    def test_a_redelivered_event_is_ignored(self):
        self.send("transfer.completed", event_id="evt_dup")
        second = self.send("transfer.completed", event_id="evt_dup")

        self.assertEqual(second, RESULT_DUPLICATE)
        self.assertEqual(WebhookEvent.objects.count(), 1)

    def test_the_same_outcome_arriving_twice_is_not_applied_twice(self):
        self.send("transfer.completed", event_id="evt_a")
        second = self.send("transfer.completed", event_id="evt_b")

        self.assertEqual(second, RESULT_DUPLICATE)

    def test_out_of_order_events_do_not_reopen_a_settled_payment(self):
        self.send("transfer.completed", event_id="evt_done")
        # A stale "failed" arrives late.
        result = self.send("transfer.failed", event_id="evt_stale")

        self.payment.refresh_from_db()

        self.assertEqual(result, RESULT_IGNORED)
        self.assertEqual(self.payment.status, PaymentStatus.SUCCESSFUL)

    def test_a_failure_hands_the_bill_back(self):
        result = self.send(
            "transfer.failed", reason="NSF", detail={"available_balance": "10.00"}
        )

        self.payment.refresh_from_db()
        self.occurrence.refresh_from_db()

        self.assertEqual(result, RESULT_APPLIED)
        self.assertEqual(self.payment.status, PaymentStatus.FAILED)
        self.assertEqual(self.payment.failure_reason, "NSF")
        self.assertEqual(self.occurrence.status, BillOccurrenceStatus.UPCOMING)

    def test_an_unknown_reference_is_recorded_but_not_applied(self):
        result = self.service.handle(
            processor="MOCK", event_id="evt_unknown",
            event_type="transfer.completed",
            payload={"reference": "SWP-19700101-9999"},
        )

        self.assertEqual(result, RESULT_UNKNOWN_PAYMENT)
        self.assertEqual(WebhookEvent.objects.count(), 1)

    def test_an_unrecognised_event_type_is_ignored(self):
        self.assertEqual(self.send("transfer.gossiped"), RESULT_IGNORED)

    def test_the_event_records_its_outcome(self):
        self.send("transfer.completed", event_id="evt_recorded")

        event = WebhookEvent.objects.get(event_id="evt_recorded")

        self.assertEqual(event.result, RESULT_APPLIED)
        self.assertIsNotNone(event.processed_at)


class LateReturnTests(TestCase):
    """ACH can claw money back days after it settled."""

    def setUp(self):
        self.user = UserFactory()
        self.bill = BillFactory(user=self.user)
        self.occurrence = BillOccurrenceFactory(
            bill=self.bill,
            status=BillOccurrenceStatus.PAID,
            paid_at=timezone.now(),
            payment_reference="SWP-20260801-0001",
        )
        self.payment = PaymentFactory(
            user=self.user,
            vendor=self.bill.vendor,
            bill_occurrence=self.occurrence,
            status=PaymentStatus.SUCCESSFUL,
            transaction_reference="SWP-20260801-0001",
        )
        self.service = WebhookService()

    def test_a_late_return_reverses_a_settled_payment(self):
        result = self.service.handle(
            processor="MOCK", event_id="evt_return",
            event_type="transfer.returned",
            payload={
                "reference": self.payment.transaction_reference,
                "reason": "R01",
            },
        )

        self.payment.refresh_from_db()

        self.assertEqual(result, RESULT_APPLIED)
        self.assertEqual(self.payment.status, PaymentStatus.RETURNED)
        self.assertEqual(self.payment.failure_reason, "R01")

    def test_the_bill_becomes_outstanding_again(self):
        self.service.handle(
            processor="MOCK", event_id="evt_return",
            event_type="transfer.returned",
            payload={"reference": self.payment.transaction_reference},
        )

        occurrence = BillOccurrence.objects.get(pk=self.occurrence.pk)

        # DUE, not UPCOMING: the money was clawed back after the due date,
        # so the bill is owed now rather than merely scheduled.
        self.assertEqual(occurrence.status, BillOccurrenceStatus.DUE)
        self.assertIsNone(occurrence.paid_at)
        self.assertEqual(occurrence.payment_reference, "")

    def test_a_return_notifies_the_user(self):
        from apps.notifications.models import Notification

        self.service.handle(
            processor="MOCK", event_id="evt_return",
            event_type="transfer.returned",
            payload={"reference": self.payment.transaction_reference},
        )

        self.assertTrue(
            Notification.objects.filter(
                title__icontains="returned"
            ).exists()
        )

    def test_a_return_on_a_payment_that_never_settled_is_ignored(self):
        self.payment.status = PaymentStatus.FAILED
        self.payment.save(update_fields=["status"])

        result = self.service.handle(
            processor="MOCK", event_id="evt_return",
            event_type="transfer.returned",
            payload={"reference": self.payment.transaction_reference},
        )

        self.assertEqual(result, RESULT_IGNORED)


@override_settings(WEBHOOK_SECRETS={"MOCK": SECRET})
class WebhookEndpointTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.payment = PaymentFactory(
            user=self.user, status=PaymentStatus.PROCESSING
        )

    def post(self, payload, signature=None):
        body = json.dumps(payload).encode()

        return self.client.post(
            "/webhooks/mock",
            data=body,
            content_type="application/json",
            HTTP_X_SWAYP_SIGNATURE=(
                signature if signature is not None else sign(body)
            ),
        )

    def test_a_signed_payload_is_accepted(self):
        response = self.post(
            {
                "id": "evt_ok",
                "type": "transfer.completed",
                "reference": self.payment.transaction_reference,
            }
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["received"])

    def test_a_bad_signature_is_rejected_and_writes_no_event(self):
        response = self.post(
            {"id": "evt_bad", "type": "transfer.completed"},
            signature="deadbeef",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_a_payload_without_an_event_id_is_rejected(self):
        response = self.post({"type": "transfer.completed"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_the_endpoint_needs_no_authentication(self):
        """A processor has no Swayp token; the signature is the trust."""
        response = self.post(
            {
                "id": "evt_anon",
                "type": "transfer.completed",
                "reference": self.payment.transaction_reference,
            }
        )

        self.assertEqual(response.status_code, 200)

    def test_the_mount_is_versionless(self):
        from django.urls import reverse

        self.assertEqual(reverse("webhook-moov"), "/webhooks/moov")
        self.assertNotIn("/api/v1", reverse("webhook-stripe"))
