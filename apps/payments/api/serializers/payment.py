"""Payment serializers (E6-S2 … E6-S6)."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.common.enums import PaymentRail
from apps.payments.models import Payment, PaymentStage
from apps.payments.services.resolution_service import ACTIONS


class PaymentCreateSerializer(serializers.Serializer):
    """Create one payment per selected occurrence (E6-S2).

    ``scheduled_for`` is what makes this a future-dated send; there is no
    separate schedule endpoint because the payload is identical.
    """

    occurrence_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False,
    )
    funding_account_id = serializers.UUIDField(required=False)
    # Omitted means each bill's own rail, from its saved payment method
    # (PAY-5). It used to default to ACH_STANDARD for everything.
    rail = serializers.ChoiceField(
        choices=PaymentRail.choices,
        required=False,
        allow_null=True,
        default=None,
    )
    scheduled_for = serializers.DateField(required=False, allow_null=True)
    # Faster check delivery for $8.99 (E9-S3). Rejected on any other rail
    # rather than ignored — see PaymentCreateService.create.
    expedited = serializers.BooleanField(required=False, default=False)


class ConfirmSerializer(serializers.Serializer):
    """The consent text actually shown, sent back verbatim (E6-S3)."""

    authorization_text = serializers.CharField(
        max_length=5000, allow_blank=False, trim_whitespace=True,
    )


class PaymentStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentStage
        fields = (
            "stage",
            "status",
            "order",
            "detail",
            "started_at",
            "finished_at",
        )


class PaymentSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(
        source="vendor.name", read_only=True, default=None,
    )
    funding_account = serializers.CharField(
        source="funding_account.masked_name", read_only=True, default=None,
    )

    class Meta:
        model = Payment
        # processor is deliberately absent: the processor name belongs only
        # inside authorization text (E6-S3).
        fields = (
            "id",
            "transaction_reference",
            "status",
            "amount",
            "fee",
            "total",
            "currency",
            "rail",
            "vendor_name",
            "funding_account",
            "bill_occurrence",
            "batch",
            "initiated_date",
            "estimated_arrival",
            "cancellation_deadline",
            "scheduled_for",
            "expedited",
            "created_at",
        )


class PaymentDetailSerializer(PaymentSerializer):
    stages = PaymentStageSerializer(many=True, read_only=True)
    receipt = serializers.SerializerMethodField()
    failure = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    # PAY-1: enough to resume an interrupted flow. Null authorized_at means
    # "not confirmed yet"; confirm_by says when it lapses.
    authorized_at = serializers.SerializerMethodField()
    authorization_text = serializers.SerializerMethodField()
    confirm_by = serializers.SerializerMethodField()

    class Meta(PaymentSerializer.Meta):
        fields = PaymentSerializer.Meta.fields + (
            "stages",
            "receipt",
            "failure",
            "progress",
            "authorized_at",
            "authorization_text",
            "confirm_by",
        )

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_authorized_at(self, obj):
        return self._selector().authorization(obj)["authorized_at"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_authorization_text(self, obj):
        return self._selector().authorization(obj)["authorization_text"]

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_confirm_by(self, obj):
        return self._selector().authorization(obj)["confirm_by"]

    def _selector(self):
        from apps.payments.selectors.payment_detail_selector import (
            PaymentDetailSelector,
        )

        return PaymentDetailSelector()

    def get_receipt(self, obj):
        return self._selector().receipt(obj)

    def get_failure(self, obj):
        return self._selector().failure_block(obj)

    def get_progress(self, obj):
        return self._selector().progress(obj)


class PaymentCreateResponseSerializer(serializers.Serializer):
    batch_id = serializers.UUIDField(allow_null=True)
    payments = PaymentSerializer(many=True)
    authorization_text = serializers.CharField()
    total = serializers.DecimalField(max_digits=18, decimal_places=2)


class ResolveSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=[(a, a) for a in ACTIONS])
    payment_method_id = serializers.UUIDField(required=False)
    funding_account_id = serializers.UUIDField(required=False)
    scheduled_for = serializers.DateField(required=False)
