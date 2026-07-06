from django.db.models import F

from .models import Wallet, WalletTransaction


class WalletRepository:
    @staticmethod
    def get_by_user(user):
        return Wallet.objects.select_for_update().get(user=user)

    @staticmethod
    def create(**kwargs):
        return Wallet.objects.create(**kwargs)

    @staticmethod
    def save(wallet):
        wallet.save()
        return wallet


class WalletTransactionRepository:
    @staticmethod
    def create(**kwargs):
        return WalletTransaction.objects.create(**kwargs)

    @staticmethod
    def list(wallet):
        return WalletTransaction.objects.filter(wallet=wallet)