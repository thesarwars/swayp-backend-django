from rest_framework import serializers

from apps.common.serializers import PaginationQuerySerializer


class NotificationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    message = serializers.CharField()
    type = serializers.CharField()
    isRead = serializers.BooleanField(source="is_read")
    createdAt = serializers.DateTimeField(source="created_at")
    readAt = serializers.DateTimeField(
        source="read_at",
        allow_null=True,
    )
    # The deep-link payload (bill_id, occurrence_id, payment_id). Without it
    # the column is write-only and the client is back to parsing the message
    # text, which is the exact thing it exists to prevent (E8-S3).
    metadata = serializers.JSONField(read_only=True)


class NotificationListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = NotificationSerializer(many=True)


class NotificationQuerySerializer(
    PaginationQuerySerializer
):
    pass


class MarkNotificationReadResponseSerializer(
    serializers.Serializer
):
    success = serializers.BooleanField()
    message = serializers.CharField()