from .models import Wallet, WalletTransaction


class WalletRepository:

    @staticmethod
    def get_by_user(user, *, for_update=False):
        queryset = Wallet.objects

        if for_update:
            queryset = queryset.select_for_update()

        

        return queryset.get(user=user)
    

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