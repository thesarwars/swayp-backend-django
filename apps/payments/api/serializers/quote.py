"""Payment quote request and response (PAY-5)."""

from rest_framework import serializers

from apps.common.enums import PaymentRail


class PaymentQuoteRequestSerializer(serializers.Serializer):
    occurrence_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=False
    )
    scheduled_for = serializers.DateField(required=False, allow_null=True)


class ExpeditedOptionSerializer(serializers.Serializer):
    fee = serializers.DecimalField(max_digits=10, decimal_places=2)
    estimated_arrival = serializers.DateField()


class RailQuoteSerializer(serializers.Serializer):
    rail = serializers.ChoiceField(choices=PaymentRail.choices)
    available = serializers.BooleanField()
    unavailable_reason = serializers.CharField(allow_null=True)
    fee = serializers.DecimalField(max_digits=10, decimal_places=2)
    initiated_date = serializers.DateField()
    estimated_arrival = serializers.DateField()
    expedited = ExpeditedOptionSerializer(
        allow_null=True, help_text="Checks only: the $8.99 faster option."
    )


class OccurrenceQuoteSerializer(serializers.Serializer):
    occurrence_id = serializers.UUIDField()
    default_rail = serializers.ChoiceField(
        choices=PaymentRail.choices,
        help_text="What POST /payments uses when rail is omitted.",
    )
    rails = RailQuoteSerializer(many=True)


class PaymentQuoteSerializer(serializers.Serializer):
    occurrences = OccurrenceQuoteSerializer(many=True)


class PaymentQuoteResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = PaymentQuoteSerializer()
