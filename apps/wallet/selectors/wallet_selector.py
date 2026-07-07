from apps.wallet.repositories import WalletRepository


class WalletSelector:

    @staticmethod
    def get_summary(user):
        return WalletRepository.get_by_user(user)