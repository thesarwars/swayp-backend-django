from apps.payments.selectors.payment_selector import (
    PaymentSelector,
)


class PaymentService:

    def __init__(self):
        self.selector = PaymentSelector()

    def payment_history(
        self,
        *,
        user,
        page,
        page_size,
    ):
        return self.selector.list_payments(
            user=user,
            page=page,
            page_size=page_size,
        )