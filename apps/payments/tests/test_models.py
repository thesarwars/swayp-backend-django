"""Payment model extensions and new entities (E6-S1)."""

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

from unittest import skipUnless

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.common.enums import PaymentStatus
from apps.payments.factories import (
    PaymentAuthorizationFactory,
    PaymentBatchFactory,
    PaymentFactory,
    PaymentStageFactory,
    WebhookEventFactory,
)
from apps.payments.models import (
    Payment,
    PaymentAuthorization,
    PaymentStage,
    WebhookEvent,
)
from apps.payments.models.reference import (
    create_with_reference,
    next_reference,
)
from apps.vendors.factories import UserFactory

D = dt.date


class ReferenceTests(TestCase):

    def test_format_is_swp_date_sequence(self):
        reference = next_reference(today=D(2026, 8, 1))

        self.assertEqual(reference, "SWP-20260801-0001")

    def test_the_sequence_increments_within_a_day(self):
        PaymentFactory(transaction_reference="SWP-20260801-0001")

        self.assertEqual(
            next_reference(today=D(2026, 8, 1)), "SWP-20260801-0002"
        )

    def test_the_sequence_restarts_each_day(self):
        PaymentFactory(transaction_reference="SWP-20260801-0007")

        self.assertEqual(
            next_reference(today=D(2026, 8, 2)), "SWP-20260802-0001"
        )

    def test_create_with_reference_assigns_the_next_one(self):
        user = UserFactory()

        payment = create_with_reference(
            lambda reference: Payment.objects.create(
                user=user,
                amount="10.00",
                total="10.00",
                transaction_reference=reference,
            ),
            today=D(2026, 8, 1),
        )

        self.assertEqual(payment.transaction_reference, "SWP-20260801-0001")

    def test_create_with_reference_recovers_from_a_taken_reference(self):
        """Losing the race: the generator hands back an already-used value.

        Patching the generator rather than inserting a row mid-build, because
        a row created inside the savepoint is rolled back with it and the
        collision would vanish.
        """
        from unittest.mock import patch

        from apps.payments.models import reference as reference_module

        user = UserFactory()
        PaymentFactory(transaction_reference="SWP-20260801-0001")

        real = reference_module.next_reference
        attempts = []

        def stale_first(today=None):
            attempts.append(1)

            if len(attempts) == 1:
                return "SWP-20260801-0001"

            return real(today)

        with patch.object(reference_module, "next_reference", stale_first):
            payment = create_with_reference(
                lambda value: Payment.objects.create(
                    user=user, amount="10.00", total="10.00",
                    transaction_reference=value,
                ),
                today=D(2026, 8, 1),
            )

        self.assertEqual(len(attempts), 2)
        self.assertEqual(payment.transaction_reference, "SWP-20260801-0002")


class ReferenceCollisionTests(TransactionTestCase):
    """The unique constraint must arbitrate, not a read-then-write."""

    reset_sequences = True

    @skipUnless(
        connection.vendor == "postgresql",
        "real concurrency needs Postgres; SQLite serialises writers",
    )
    def test_concurrent_creates_do_not_collide(self):
        user = UserFactory()

        def make(_):
            try:
                return create_with_reference(
                    lambda reference: Payment.objects.create(
                        user=user, amount="10.00", total="10.00",
                        transaction_reference=reference,
                    ),
                    today=D(2026, 8, 1),
                ).transaction_reference
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=5) as pool:
            references = list(pool.map(make, range(5)))

        self.assertEqual(len(set(references)), 5)
        self.assertEqual(Payment.objects.count(), 5)


class PaymentFieldTests(TestCase):

    def test_provider_and_category_are_optional(self):
        """A vendor-only payment has no directory provider behind it."""
        payment = PaymentFactory()

        self.assertIsNone(payment.provider)
        self.assertIsNone(payment.category)
        payment.full_clean(exclude=["provider", "category"])

    def test_in_flight_and_terminal_helpers(self):
        in_flight = [
            PaymentStatus.SCHEDULED,
            PaymentStatus.PENDING,
            PaymentStatus.PROCESSING,
        ]
        terminal = [
            PaymentStatus.SUCCESSFUL,
            PaymentStatus.FAILED,
            PaymentStatus.CANCELLED,
            PaymentStatus.REFUNDED,
            PaymentStatus.RETURNED,
        ]

        for status in in_flight:
            with self.subTest(status=status):
                payment = PaymentFactory(status=status)
                self.assertTrue(payment.is_in_flight)
                self.assertFalse(payment.is_terminal)

        for status in terminal:
            with self.subTest(status=status):
                payment = PaymentFactory(status=status)
                self.assertTrue(payment.is_terminal)
                self.assertFalse(payment.is_in_flight)

    def test_a_retry_points_at_the_payment_it_replaces(self):
        original = PaymentFactory(status=PaymentStatus.FAILED)
        retry = PaymentFactory(retry_of=original)

        self.assertEqual(list(original.retries.all()), [retry])


class PaymentStageTests(TestCase):

    def test_a_stage_cannot_repeat_on_one_payment(self):
        stage = PaymentStageFactory()

        with self.assertRaises(IntegrityError):
            PaymentStage.objects.create(
                payment=stage.payment, stage=stage.stage, order=1
            )

    def test_stages_order_for_the_drawer(self):
        payment = PaymentFactory()

        for order, name in enumerate(
            ["AUTHORIZED", "DEBITING", "ROUTING", "COMPLETED"], start=1
        ):
            PaymentStageFactory(payment=payment, stage=name, order=order)

        self.assertEqual(
            [s.stage for s in payment.stages.all()],
            ["AUTHORIZED", "DEBITING", "ROUTING", "COMPLETED"],
        )


class PaymentAuthorizationTests(TestCase):

    def test_consent_is_immutable(self):
        authorization = PaymentAuthorizationFactory()
        authorization.authorization_text = "rewritten"

        with self.assertRaises(ValueError):
            authorization.save()

        authorization.refresh_from_db()
        self.assertNotEqual(authorization.authorization_text, "rewritten")

    def test_it_attaches_to_a_payment_or_a_batch_but_not_both(self):
        payment = PaymentFactory()
        batch = PaymentBatchFactory()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentAuthorization.objects.create(
                    payment=payment, batch=batch,
                    authorization_text="both",
                    accepted_at=timezone.now(), ip="203.0.113.9",
                )

    def test_it_requires_one_of_them(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentAuthorization.objects.create(
                    authorization_text="neither",
                    accepted_at=timezone.now(), ip="203.0.113.9",
                )

    def test_a_batch_authorization_is_valid(self):
        batch = PaymentBatchFactory(count=6, total="9600.00")

        authorization = PaymentAuthorization.objects.create(
            batch=batch,
            authorization_text="I authorize Swayp to debit 6 bills.",
            accepted_at=timezone.now(),
            ip="203.0.113.9",
        )

        self.assertEqual(batch.authorizations.count(), 1)
        self.assertIsNone(authorization.payment)

    def test_a_payment_with_consent_cannot_be_deleted(self):
        """PROTECT — deleting the payment would orphan the evidence."""
        authorization = PaymentAuthorizationFactory()

        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError):
            authorization.payment.delete()


class WebhookEventTests(TestCase):

    def test_the_same_event_cannot_be_recorded_twice(self):
        event = WebhookEventFactory()

        with self.assertRaises(IntegrityError):
            WebhookEvent.objects.create(
                processor=event.processor, event_id=event.event_id
            )

    def test_the_same_id_from_a_different_processor_is_distinct(self):
        event = WebhookEventFactory(processor="MOOV")
        WebhookEventFactory(processor="STRIPE", event_id=event.event_id)

        self.assertEqual(WebhookEvent.objects.count(), 2)
