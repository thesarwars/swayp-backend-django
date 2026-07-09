from apps.payments.selectors.payment_selector import (
    PaymentSelector,
)
from decimal import Decimal
from uuid import uuid4
from django.utils import timezone
from apps.payment_tracking.repositories import (
    PaymentTrackingRepository,
)

from apps.payments.services.payment_state_service import (
    PaymentStateService,
)

from django.db import transaction
from apps.common.exceptions import(
    InsufficientBalanceException,
    BadRequestException,
)

from apps.common.enums import( 
    PaymentStatus,
    ProviderStatus,
    WalletStatus,
)
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

from apps.notifications.models import Notification
from apps.payment_tracking.models import PaymentTracking


class PaymentService:

    def __init__(self):
        self.selector = PaymentSelector()
        self.repository = PaymentRepository()

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
        provider_id,
        category_id,
        amount,
        payment_method,
):
        provider = self.repository.get_provider(
            provider_id,
        )

        category = self.repository.get_category(
            category_id,
        )

        if provider.category_id != category.id:
            raise BadRequestException(
                "Provider does not belong to this category."
            )

        wallet = WalletRepository.get_by_user(
            user,
            for_update=True,
        )

        if wallet.status != WalletStatus.ACTIVE:
            raise BadRequestException(
                "Wallet is not active."
            )

        amount = Decimal(amount)

        if wallet.balance < amount:
            raise InsufficientBalanceException()

        reference = uuid4().hex.upper()

        payment = self.repository.create(
            user=user,
            provider=provider,
            category=category,
            amount=amount,
            fee=Decimal("0.00"),
            total=amount,
            currency=wallet.currency,
            payment_method=payment_method,
            status=PaymentStatus.PENDING,
            transaction_reference=reference,
        )

        PaymentTracking.objects.create(
            payment=payment,
            status=PaymentStatus.PENDING,
        )

        before = wallet.balance
        wallet.balance -= amount
        WalletRepository.save(wallet)

        WalletTransactionRepository.create(
            wallet=wallet,
            payment=payment,
            amount=amount,
            balance_before=before,
            balance_after=wallet.balance,
            transaction_type="PAYMENT",
            status=PaymentStatus.PENDING,
            reference=reference,
            description=f"Payment to {provider.provider_name}",
        )

        Notification.objects.create(
            user=user,
            title="Payment Initiated",
            message=f"Your payment to {provider.provider_name} has been initiated.",
            type="PAYMENT",
        )

        return payment
    

    @transaction.atomic
    def mark_processing(
        self,
        *,
        user,
        payment_id,
    ):
        payment = self.repository.get_for_update(
            payment_id=payment_id,
            user=user,
        )

        PaymentStateService.to_processing(
        payment,

        )

        PaymentRepository.update_status(
        payment=payment,
        status=PaymentStatus.PROCESSING,
        )

        tracking = (
            PaymentTrackingRepository()
            .get_by_payment_for_update(
                payment=payment,
            )
        )

        PaymentTrackingRepository.update_status(
            tracking=tracking,
            status=PaymentStatus.PROCESSING,
            estimated_completion=timezone.now(),
        )

        Notification.objects.create(
            user=user,
            title="Payment Processing",
            message=f"Payment {payment.transaction_reference} is being processed.",
            type="PAYMENT",
        )

        return payment
    

    @transaction.atomic
    def mark_successful(
        self,
        *,
        user,
        payment_id,
    ):
        payment = self.repository.get_for_update(
            payment_id=payment_id,
            user=user,
        )

        PaymentStateService.to_success(
            payment,
        )

        PaymentRepository.update_status(
            payment=payment,
            status=PaymentStatus.SUCCESSFUL,
            provider_reference=uuid4().hex.upper(),
        )
        tracking = (
            PaymentTrackingRepository()
            .get_by_payment_for_update(
                payment=payment,
            )
        )

        PaymentTrackingRepository.update_status(
            tracking=tracking,
            status=PaymentStatus.SUCCESSFUL,
        )

        wallet_transaction = (
            WalletTransactionRepository.get_by_payment(
                payment
            )
        )   

        wallet_transaction.status = (
            PaymentStatus.SUCCESSFUL
        )

        wallet_transaction.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        Notification.objects.create(
            user=user,
            title="Payment Successful",
            message=(
                f"Payment "
                f"{payment.transaction_reference} "
                f"completed successfully."
            ),
            type="PAYMENT",
        )

        return payment