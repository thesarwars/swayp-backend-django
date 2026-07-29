"""E8-S4 — the reconciliation, pinned so it cannot be quietly undone.

`ReminderService` was unwired dead code that wrote Notification rows directly,
first fired on the due date (already past the ACH initiation date) and had no
dedupe. Its behaviour now lives in notifications.bill_status_notifier. What
this file protects is the *count*: exactly one producer of "this bill is due".
"""

from django.test import SimpleTestCase

from apps.common.enums import PaymentStatus
from apps.payments.selectors import (
    IN_FLIGHT_PAYMENT_STATUSES,
    SILENCING_PAYMENT_STATUSES,
)
from apps.payments.services import autopay_service


class ReminderServiceRemovalTests(SimpleTestCase):

    def test_reminder_service_is_gone(self):
        """Two producers of "this bill is due" is a shipped duplicate."""
        self.assertFalse(hasattr(autopay_service, "ReminderService"))

    def test_rail_for_bill_is_importable_at_module_scope(self):
        """The reminder window is measured from initiation_date(due, rail)."""
        self.assertTrue(callable(autopay_service.rail_for_bill))

    def test_the_silence_set_is_the_in_flight_set_plus_settled(self):
        """Carried over verbatim from the deleted ReminderService."""
        self.assertEqual(
            IN_FLIGHT_PAYMENT_STATUSES,
            (
                PaymentStatus.SCHEDULED,
                PaymentStatus.PENDING,
                PaymentStatus.PROCESSING,
            ),
        )
        self.assertEqual(
            SILENCING_PAYMENT_STATUSES,
            IN_FLIGHT_PAYMENT_STATUSES + (PaymentStatus.SUCCESSFUL,),
        )
        # FAILED must never silence: an overdue bill whose payment failed is
        # exactly the case the late-fee countdown exists for.
        self.assertNotIn(PaymentStatus.FAILED, SILENCING_PAYMENT_STATUSES)
