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
        status=None,
        provider_id=None,
        category_id=None,
        from_date=None,
        to_date=None,
        search=None,
    ):
        return self.selector.list_payments(
            user=user,
            page=page,
            page_size=page_size,
            status=status,
            provider_id=provider_id,
            category_id=category_id,
            from_date=from_date,
            to_date=to_date,
            search=search,
        )