from decimal import Decimal

from django.db import transaction

from apps.common.enums import WalletStatus

from .repositories import (
    WalletRepository,
    WalletTransactionRepository,
)


class WalletService:
    @staticmethod
    def get_summary(user):
        return WalletRepository.get_by_user(user)

    @staticmethod
    @transaction.atomic
    def deposit(wallet, amount, reference, description=""):
        wallet = WalletRepository.get_by_user(wallet.user)

        before = wallet.balance
        after = before + Decimal(amount)

        wallet.balance = after
        WalletRepository.save(wallet)

        WalletTransactionRepository.create(
            wallet=wallet,
            amount=amount,
            balance_before=before,
            balance_after=after,
            transaction_type="DEPOSIT",
            reference=reference,
            description=description,
        )

        return wallet

    @staticmethod
    @transaction.atomic
    def withdraw(wallet, amount, reference, description=""):
        wallet = WalletRepository.get_by_user(wallet.user)

        if wallet.status != WalletStatus.ACTIVE:
            raise ValueError("Wallet is not active.")

        if wallet.balance < amount:
            raise ValueError("Insufficient balance.")

        before = wallet.balance
        after = before - amount

        wallet.balance = after
        WalletRepository.save(wallet)

        WalletTransactionRepository.create(
            wallet=wallet,
            amount=amount,
            balance_before=before,
            balance_after=after,
            transaction_type="WITHDRAW",
            reference=reference,
            description=description,
        )

        return wallet