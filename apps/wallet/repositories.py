from apps.common.exceptions import NotFoundException
from .models import Wallet, WalletTransaction


class WalletRepository:

    @staticmethod
    def get_by_user(user, *, for_update=False):
        queryset = Wallet.objects

        if for_update:
            queryset = queryset.select_for_update()

        try:
            return queryset.get(user=user)
        except Wallet.DoesNotExist:
            raise NotFoundException("Wallet not found.")
    

    @staticmethod
    def save(wallet):
        wallet.save(
            update_fields=[
                "balance",
                "updated_at",
            ]
        )
        return wallet


class WalletTransactionRepository:

    @staticmethod
    def create(**kwargs):
        return WalletTransaction.objects.create(**kwargs)

    @staticmethod
    def get_queryset(wallet):
        return (
            WalletTransaction.objects
            .filter(wallet=wallet)
            .order_by("-created_at")
        )
    
    @classmethod
    def get_by_payment(
        cls,
        payment,
        *,
        for_update=False,
    ):
        queryset = cls.get_queryset()

        if for_update:
            queryset = queryset.select_for_update()

        try:
            return queryset.get(
                payment=payment,
            )
        except WalletTransaction.DoesNotExist:
            raise NotFoundException(
                "Wallet transaction not found."
            )
        

    @staticmethod
    def update_balance(
        wallet,
        balance,
    ):
        wallet.balance = balance

        wallet.save(
            update_fields=[
                "balance",
                "updated_at",
            ]
        )

        return wallet