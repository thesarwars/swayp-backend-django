from rest_framework import serializers


class PaginationQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(default=1, min_value=1)
    pageSize = serializers.IntegerField(default=20, min_value=1, max_value=100)


class PaginationResponseSerializer(serializers.Serializer):
    page = serializers.IntegerField()
    pageSize = serializers.IntegerField()
    totalItems = serializers.IntegerField()
    totalPages = serializers.IntegerField()


class SuccessResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()


class ErrorResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    errors = serializers.DictField(required=False)