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
    success = serializers.BooleanField()
    message = serializers.CharField()
    errors = serializers.DictField(required=False)