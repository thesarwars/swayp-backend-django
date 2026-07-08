from apps.common.pagination import PaginationService

from apps.payment_tracking.repositories import (
    PaymentTrackingRepository,
)


class PaymentTrackingSelector:

    def __init__(self):
        self.repository = PaymentTrackingRepository()

    def list_tracking(
        self,
        *,
        user,
        page=1,
        page_size=20,
    ):
        queryset = self.repository.list_by_user(
            user=user,
        )

        return PaginationService.paginate(
            queryset=queryset,
            page=page,
            page_size=page_size,
        )

    def get_tracking(
        self,
        *,
        user,
        payment_id,
    ):
        return self.repository.get_by_payment(
            user=user,
            payment_id=payment_id,
        )