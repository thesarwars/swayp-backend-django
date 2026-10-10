from rest_framework import serializers

from apps.common.casing import SnakeCaseInputMixin, snake_case_aliases


class PaginationQuerySerializer(SnakeCaseInputMixin, serializers.Serializer):
    page = serializers.IntegerField(default=1, min_value=1)
    pageSize = serializers.IntegerField(default=20, min_value=1, max_value=100)


@snake_case_aliases
class PaginationResponseSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    pageSize = serializers.IntegerField()
    totalItems = serializers.IntegerField()
    totalPages = serializers.IntegerField()
    hasNext = serializers.BooleanField()
    hasPrevious = serializers.BooleanField()


class SuccessResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()


class ErrorResponseSerializer(serializers.Serializer):
    """Every error body (API-3, API-4)."""

    success = serializers.BooleanField(help_text="Always false.")
    message = serializers.CharField()
    code = serializers.CharField(
        help_text="Stable machine-readable code; branch on this."
    )
    errors = serializers.DictField(
        required=False,
        help_text="Per field, a list of messages. Nested fields nest.",
    )