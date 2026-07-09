from apps.common.enums import PaymentStatus

from apps.common.exceptions import (
    InvalidPaymentStateException,
    PaymentAlreadyRefundedException,
    PaymentNotRefundableException,
)


class PaymentStateMachine:

    TRANSITIONS = {
        PaymentStatus.PENDING: {
            PaymentStatus.PROCESSING,
        },
        PaymentStatus.PROCESSING: {
            PaymentStatus.SUCCESSFUL,
            PaymentStatus.FAILED,
        },
        PaymentStatus.SUCCESSFUL: {
            PaymentStatus.REFUNDED,
        },
        PaymentStatus.FAILED: set(),
        PaymentStatus.REFUNDED: set(),
        PaymentStatus.CANCELLED: set(),
    }

    @classmethod
    def validate(
        cls,
        current,
        target,
    ):
        if current == PaymentStatus.REFUNDED:
            raise PaymentAlreadyRefundedException()

        if (
            target == PaymentStatus.REFUNDED
            and current != PaymentStatus.SUCCESSFUL
        ):
            raise PaymentNotRefundableException()

        allowed = cls.TRANSITIONS.get(
            current,
            set(),
        )

        if target not in allowed:
            raise InvalidPaymentStateException(
                (
                    f"Cannot change payment status "
                    f"from {current} to {target}."
                )
            )