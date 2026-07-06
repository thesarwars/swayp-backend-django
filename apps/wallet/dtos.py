from rest_framework import serializers

from .models import Wallet


class WalletSummaryResponseDTO(serializers.ModelSerializer):
    walletStatus = serializers.CharField(source="status")
    rewardPoints = serializers.IntegerField(source="reward_points")
    updatedAt = serializers.DateTimeField(source="updated_at")

    class Meta:
        model = Wallet
        fields = (
            "balance",
            "currency",
            "walletStatus",
            "rewardPoints",
            "cashback",
            "updatedAt",
        )