from apps.common.pagination import PaginationService

from apps.payments.repositories import PaymentRepository


class PaymentSelector:

    def __init__(self):
        self.repository = PaymentRepository()

    def list_payments(
        self,
        *,
        user,
        page=1,
        page_size=20,
    ):
        queryset = self.repository.list_by_user(
            user
        )

        return PaginationService.paginate(
            queryset=queryset,
            page=page,
            page_size=page_size,
        )

    def get_payment(
        self,
        *,
        user,
        payment_id,
    ):
        return self.repository.get_by_id(
            user=user,
            payment_id=payment_id,
        )