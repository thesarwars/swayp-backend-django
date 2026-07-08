from apps.payments.selectors.payment_selector import (
    PaymentSelector,
)
from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from apps.common.exceptions import(
    InsufficientBalanceException
)

from apps.common.enums import PaymentStatus
from apps.providers.repositories import (
    ProviderRepository,
)
from apps.wallet.repositories import (
    WalletRepository,
    WalletTransactionRepository,
)
from apps.payment_tracking.models import (
    PaymentTracking,
)
from apps.payments.repositories import(
    PaymentRepository
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
    
    @transaction.atomic
    def create_payment(
        self,
        *,
        user,
        provider,
        category,
        amount,
        payment_method,
    ):
        wallet = WalletRepository.get_by_user(
            user,
            for_update=True,
        )

        amount = Decimal(amount)

        if wallet.balance < amount:
            raise InsufficientBalanceException()

        reference = uuid4().hex.upper()

        payment = PaymentRepository.create_payment(
            user=user,
            provider=provider,
            category=category,
            amount=amount,
            fee=Decimal("0.00"),
            total=amount,
            currency=wallet.currency,
            status=PaymentStatus.PENDING,
            transaction_reference=reference,
            payment_method=payment_method,
        )

        PaymentTracking.objects.create(
            payment=payment,
            status=PaymentStatus.PENDING,
        )

        before = wallet.balance
        after = before - amount

        wallet.balance = after
        WalletRepository.save(wallet)

        WalletTransactionRepository.create(
            wallet=wallet,
            payment=payment,
            amount=amount,
            balance_before=before,
            balance_after=after,
            transaction_type="PAYMENT",
            status=PaymentStatus.PENDING,
            reference=reference,
            description="Bill payment",
        )

        return payment