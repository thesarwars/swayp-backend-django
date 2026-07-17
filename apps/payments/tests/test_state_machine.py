from django.test import SimpleTestCase

from apps.common.enums import PaymentStatus
from apps.common.exceptions import (
    InvalidPaymentStateException,
    PaymentAlreadyRefundedException,
    PaymentNotRefundableException,
)
from apps.payments.state_machine import PaymentStateMachine

S = PaymentStatus

# Every legal (from -> to) transition per E1-S3.
LEGAL = {
    (S.SCHEDULED, S.PENDING),
    (S.SCHEDULED, S.CANCELLED),
    (S.PENDING, S.PROCESSING),
    (S.PENDING, S.CANCELLED),
    (S.PROCESSING, S.SUCCESSFUL),
    (S.PROCESSING, S.FAILED),
    (S.PROCESSING, S.CANCELLED),
    (S.SUCCESSFUL, S.REFUNDED),
    (S.SUCCESSFUL, S.RETURNED),
}


class PaymentStateMachineTests(SimpleTestCase):

    def test_every_pair_is_legal_or_rejected(self):
        for current in S.values:
            for target in S.values:
                pair = (current, target)
                with self.subTest(current=current, target=target):
                    if pair in LEGAL:
                        # Should not raise.
                        PaymentStateMachine.validate(current, target)
                    else:
                        with self.assertRaises(
                            InvalidPaymentStateException
                        ):
                            PaymentStateMachine.validate(
                                current, target
                            )

    def test_terminal_states_have_no_exits(self):
        for terminal in (
            S.FAILED,
            S.RETURNED,
            S.REFUNDED,
            S.CANCELLED,
        ):
            self.assertEqual(
                PaymentStateMachine.TRANSITIONS[terminal],
                set(),
            )

    def test_scheduled_can_reach_pending_and_cancelled(self):
        PaymentStateMachine.validate(S.SCHEDULED, S.PENDING)
        PaymentStateMachine.validate(S.SCHEDULED, S.CANCELLED)

    def test_cancellation_reachable_from_active_states(self):
        for current in (S.SCHEDULED, S.PENDING, S.PROCESSING):
            PaymentStateMachine.validate(current, S.CANCELLED)

    def test_late_return_after_success(self):
        PaymentStateMachine.validate(S.SUCCESSFUL, S.RETURNED)

    def test_already_refunded_is_specific_exception(self):
        with self.assertRaises(PaymentAlreadyRefundedException):
            PaymentStateMachine.validate(S.REFUNDED, S.PENDING)

    def test_refund_only_from_successful(self):
        with self.assertRaises(PaymentNotRefundableException):
            PaymentStateMachine.validate(S.PENDING, S.REFUNDED)
        # Legal from SUCCESSFUL:
        PaymentStateMachine.validate(S.SUCCESSFUL, S.REFUNDED)
