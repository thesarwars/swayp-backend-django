from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.banking.models import (
    BankAccount,
    BankConnection,
    BillDetectionCandidate,
    TransactionScan,
)
from apps.common.enums import BillFrequency


class LinkTokenRequestSerializer(serializers.Serializer):
    """Optional. Which client is opening Plaid Link, so an OAuth bank can hand
    the user back to it (BANK-5). Omitted means web."""

    platform = serializers.ChoiceField(
        choices=["ios", "android", "web"], required=False
    )


class LinkTokenSerializer(serializers.Serializer):
    link_token = serializers.CharField()
    expiration = serializers.CharField(allow_null=True)
    provider = serializers.CharField()
    # The history window a scan reads (BANK-4), returned before the link so
    # the pre-link copy ("Returns 24 months of history") can come from data.
    months_history = serializers.IntegerField()


class InstitutionSerializer(serializers.Serializer):
    """One row of the bank picker."""

    institution_id = serializers.CharField()
    name = serializers.CharField()
    logo = serializers.CharField(allow_null=True)
    subtitle = serializers.CharField(allow_blank=True)


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


class LatestScanSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()


class BankConnectionSerializer(serializers.ModelSerializer):
    accounts = BankAccountSerializer(many=True, read_only=True)
    # The way back to a connection's detected bills (BANK-6): a user who
    # links and leaves, or a client that lost the exchange answer, finds the
    # scan here instead of starting a new one.
    latest_scan = serializers.SerializerMethodField()

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
            "latest_scan",
            "created_at",
        )

    @extend_schema_field(LatestScanSerializer(allow_null=True))
    def get_latest_scan(self, connection):
        # list_connections prefetches the scans newest-first, so a list is
        # one query; a single connection falls back to its own.
        prefetched = getattr(connection, "scans_newest_first", None)

        if prefetched is not None:
            scan = prefetched[0] if prefetched else None
        else:
            scan = connection.scans.order_by("-created_at").first()

        if scan is None:
            return None

        return {"id": scan.id, "status": scan.status}


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
            "error_code",
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
            "stages": self.get_stages(obj),
        }

    def get_stages(self, obj):
        """The four steps the Verifying/Scanning screens draw.

        Derived from what the scan has actually done, not from a timer. A
        timer advances whether or not anything is happening, so a stuck scan
        looks identical to a fast one and the bar is decoration.

        Each stage is done / active / pending, and only one is ever active —
        the screen renders the list rather than deciding the sequence.
        """
        from apps.common.enums import ScanStatus

        failed = obj.status == ScanStatus.FAILED
        complete = obj.status == ScanStatus.DONE

        # Nothing is "active" on a finished scan, and on a failed one the
        # stage that was running is where it stopped.
        reached = [
            # The connection exists for a scan to belong to at all.
            True,
            True,
            obj.transactions_scanned > 0 or complete,
            obj.detected_count > 0 or complete,
        ]

        labels = (
            ("connected", "Connected to your bank"),
            ("verifying", "Verifying account ownership"),
            ("history", "Retrieving transaction history"),
            ("detecting", "Detecting recurring bills"),
        )

        stages = []
        active_taken = False

        for (key, label), done in zip(labels, reached):
            if complete:
                state = "done"
            elif done:
                state = "done"
            elif failed:
                state = "failed" if not active_taken else "pending"
                active_taken = True
            elif not active_taken:
                state = "active"
                active_taken = True
            else:
                state = "pending"

            stages.append({"key": key, "label": label, "status": state})

        return stages


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


class CandidateUpdateSerializer(serializers.Serializer):
    """Correct a detected bill before importing it (BANK-8).

    Partial: send only what changed. These are the fields import turns into
    the bill, so an edit here is what the bill gets.
    """

    amount = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )
    category = serializers.UUIDField(required=False)
    cadence = serializers.ChoiceField(
        choices=BillFrequency.choices, required=False
    )
    due_day = serializers.IntegerField(
        min_value=1,
        max_value=31,
        required=False,
        help_text=(
            "Day of the month (1-31); for WEEKLY, the ISO weekday "
            "(1 = Monday … 7 = Sunday)."
        ),
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Send at least one field to update."
            )

        return attrs


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
