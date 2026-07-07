from decimal import Decimal

from django.db import transaction

from apps.common.enums import WalletStatus
from apps.common.exceptions import (
    BadRequestException,
    InsufficientBalanceException,
)
from apps.wallet.models import WalletTransaction
from apps.wallet.repositories import (
    WalletRepository,
    WalletTransactionRepository,
)
from apps.wallet.selectors.wallet_selector import WalletSelector


class WalletService:

    def __init__(self):
        self.selector = WalletSelector()

    def get_summary(self, user):
        return self.selector.get_summary(user)

    @transaction.atomic
    def deposit(
        self,
        *,
        wallet,
        amount,
        reference,
        description="",
    ):
        wallet = WalletRepository.get_by_user(
            wallet.user,
            for_update=True,
        )

        amount = Decimal(amount)

        before = wallet.balance
        after = before + amount

        wallet.balance = after
        WalletRepository.save(wallet)

        WalletTransactionRepository.create(
            wallet=wallet,
            amount=amount,
            balance_before=before,
            balance_after=after,
            transaction_type=WalletTransaction.TransactionType.DEPOSIT,
            reference=reference,
            description=description,
        )

        return wallet

    @transaction.atomic
    def withdraw(
        self,
        *,
        wallet,
        amount,
        reference,
        description="",
    ):
        wallet = WalletRepository.get_by_user(
            wallet.user,
            for_update=True,
        )

        amount = Decimal(amount)

        if wallet.status != WalletStatus.ACTIVE:
            raise BadRequestException(
                "Wallet is not active."
            )

        if wallet.balance < amount:
            raise InsufficientBalanceException()

        before = wallet.balance
        after = before - amount

        wallet.balance = after
        WalletRepository.save(wallet)

        WalletTransactionRepository.create(
            wallet=wallet,
            amount=amount,
            balance_before=before,
            balance_after=after,
            transaction_type=WalletTransaction.TransactionType.WITHDRAW,
            reference=reference,
            description=description,
        )

        return wallet