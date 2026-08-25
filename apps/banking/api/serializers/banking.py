from rest_framework import serializers

from apps.banking.models import (
    BankAccount,
    BankConnection,
    BillDetectionCandidate,
    TransactionScan,
)


class LinkTokenSerializer(serializers.Serializer):
    link_token = serializers.CharField()
    expiration = serializers.CharField(allow_null=True)
    provider = serializers.CharField()


class LinkExchangeSerializer(serializers.Serializer):
    """Consent is mandatory — see E5-S2."""

    public_token = serializers.CharField(max_length=255)
    consent_accepted = serializers.BooleanField()


class BankAccountSerializer(serializers.ModelSerializer):
    """Masked only. There is no field here that reveals a full number."""

    display = serializers.CharField(source="masked_name", read_only=True)

    class Meta:
        model = BankAccount
        fields = (
            "id",
            "name",
            "mask",
            "display",
            "account_type",
            "is_default_funding_source",
            "available_balance",
            "current_balance",
            "balance_as_of",
        )


class BankConnectionSerializer(serializers.ModelSerializer):
    accounts = BankAccountSerializer(many=True, read_only=True)

    class Meta:
        model = BankConnection
        # access_token is deliberately absent and must stay that way.
        fields = (
            "id",
            "provider",
            "institution_name",
            "institution_logo",
            "status",
            "consented_at",
            "accounts",
            "created_at",
        )


class TransactionScanSerializer(serializers.ModelSerializer):
    progress = serializers.SerializerMethodField()

    class Meta:
        model = TransactionScan
        fields = (
            "id",
            "status",
            "months_history",
            "transactions_scanned",
            "detected_count",
            "error_message",
            "completed_at",
            "created_at",
            "progress",
        )

    def get_progress(self, obj):
        from apps.banking.services.scan_service import ScanService

        return {
            "is_complete": obj.status != "RUNNING",
            "thin_history": ScanService().is_thin_history(obj),
        }


class StartScanSerializer(serializers.Serializer):
    connection_id = serializers.UUIDField()
    months = serializers.IntegerField(
        required=False, min_value=1, max_value=24,
    )


class BillDetectionCandidateSerializer(serializers.ModelSerializer):
    category_guess_name = serializers.CharField(
        source="category_guess.name", read_only=True, default=None,
    )
    is_imported = serializers.BooleanField(read_only=True)

    class Meta:
        model = BillDetectionCandidate
        fields = (
            "id",
            "vendor_name",
            "category_guess",
            "category_guess_name",
            "cadence",
            "due_day",
            "amount",
            "occurrences",
            "selected",
            "is_imported",
            "imported_bill",
        )


class ImportCandidatesSerializer(serializers.Serializer):
    candidate_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=False,
    )
    all = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if not attrs.get("all") and not attrs.get("candidate_ids"):
            raise serializers.ValidationError(
                {"candidate_ids": "Provide candidate_ids or set all=true."}
            )

        return attrs


class SetFundingSourceSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
