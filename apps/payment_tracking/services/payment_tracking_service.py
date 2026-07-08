from apps.payment_tracking.selectors.payment_tracking_selector import (
    PaymentTrackingSelector,
)


class PaymentTrackingService:

    def __init__(self):
        self.selector = PaymentTrackingSelector()

    def list_tracking(
        self,
        *,
        user,
        page,
        page_size,
    ):
        return self.selector.list_tracking(
            user=user,
            page=page,
            page_size=page_size,
        )