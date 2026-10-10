"""Response shapes for the onboarding summary and bill import (BANK-2).

Documentation only: the views build these bodies from selectors and
services, and these serializers describe them to OpenAPI. Field for field
what OnboardingSelector.summary and BillImportService.import_candidates
return.
"""

from rest_framework import serializers


class FundingAccountSerializer(serializers.Serializer):
    account_id = serializers.UUIDField()
    name = serializers.CharField()
    mask = serializers.CharField()
    display = serializers.CharField()


class OnboardingConnectionSerializer(serializers.Serializer):
    connection_id = serializers.UUIDField()
    institution_name = serializers.CharField()
    institution_logo = serializers.CharField(
        allow_blank=True, help_text="URL, or empty when the provider has none."
    )
    status = serializers.CharField()
    connected_at = serializers.DateTimeField(
        allow_null=True, help_text="When the user consented to the link."
    )
    account_count = serializers.IntegerField()
    funding_account = FundingAccountSerializer(allow_null=True)


class OnboardingDetectionSerializer(serializers.Serializer):
    detected = serializers.IntegerField()
    imported = serializers.IntegerField()
    pending = serializers.IntegerField()


class OnboardingBillsSerializer(serializers.Serializer):
    total_due_this_month = serializers.DecimalField(
        max_digits=12, decimal_places=2
    )
    overdue_count = serializers.IntegerField()
    due_count = serializers.IntegerField()
    upcoming_count = serializers.IntegerField()


class RailReadinessSerializer(serializers.Serializer):
    """Each active vendor counted once, by its best rail:
    network, else ACH, else check, else needs_details."""

    total_vendors = serializers.IntegerField()
    network_matched = serializers.IntegerField()
    ach_captured = serializers.IntegerField()
    check_ready = serializers.IntegerField()
    needs_details = serializers.IntegerField(
        help_text="Vendors with no payment method, which cannot be paid yet."
    )


class OnboardingSummarySerializer(serializers.Serializer):
    connection = OnboardingConnectionSerializer(
        allow_null=True, help_text="The newest ACTIVE connection, or null."
    )
    detection = OnboardingDetectionSerializer()
    bills = OnboardingBillsSerializer()
    rail_readiness = RailReadinessSerializer()


class OnboardingSummaryResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = OnboardingSummarySerializer()


class ImportedBillSerializer(serializers.Serializer):
    candidate_id = serializers.UUIDField()
    vendor_name = serializers.CharField()
    bill_id = serializers.UUIDField()
    vendor_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    anchor_date = serializers.DateField()


class SkippedCandidateSerializer(serializers.Serializer):
    candidate_id = serializers.UUIDField()
    vendor_name = serializers.CharField()
    bill_id = serializers.UUIDField(
        help_text="The bill an earlier import already created."
    )
    reason = serializers.CharField(help_text="Today always already_imported.")


class ImportReportSerializer(serializers.Serializer):
    scan_id = serializers.UUIDField()
    imported_count = serializers.IntegerField()
    skipped_count = serializers.IntegerField()
    imported = ImportedBillSerializer(many=True)
    skipped = SkippedCandidateSerializer(many=True)


class ImportResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = ImportReportSerializer()
