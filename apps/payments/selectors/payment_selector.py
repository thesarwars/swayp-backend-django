from apps.common.pagination import PaginationService

from apps.payments.repositories import (
    PaymentRepository,
)


class PaymentSelector:

    def __init__(self):
        self.repository = PaymentRepository()

    def list_payments(
        self,
        *,
        user,
        page=1,
        page_size=20,
        status=None,
        provider_id=None,
        category_id=None,
        from_date=None,
        to_date=None,
        search=None,
    ):
        queryset = self.repository.list_by_user(
            user=user,
            status=status,
            provider_id=provider_id,
            category_id=category_id,
            from_date=from_date,
            to_date=to_date,
            search=search,
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