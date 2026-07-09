from apps.common.enums import PaymentStatus

from apps.payments.state_machine import (
    PaymentStateMachine,
)


class PaymentStateService:

    @staticmethod
    def to_processing(payment):
        PaymentStateMachine.validate(
            payment.status,
            PaymentStatus.PROCESSING,
        )

    @staticmethod
    def to_success(payment):
        PaymentStateMachine.validate(
            payment.status,
            PaymentStatus.SUCCESSFUL,
        )

    @staticmethod
    def to_failed(payment):
        PaymentStateMachine.validate(
            payment.status,
            PaymentStatus.FAILED,
        )

    @staticmethod
    def to_refunded(payment):
        PaymentStateMachine.validate(
            payment.status,
            PaymentStatus.REFUNDED,
        )