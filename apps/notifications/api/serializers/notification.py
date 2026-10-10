from rest_framework import serializers

from apps.common.enums import NotificationCategory, NotificationType
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
    # Repeatable: ?type=BILL_DUE&type=PAYMENT_FAILED.
    type = serializers.ListField(
        child=serializers.ChoiceField(choices=NotificationType.choices),
        required=False,
    )
    category = serializers.ChoiceField(
        choices=NotificationCategory.choices,
        required=False,
    )
    # allow_null so an absent isRead means "both". Without it DRF reads a
    # missing boolean query param as false and the list would silently drop
    # every read notification.
    isRead = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
    )


class MarkNotificationReadResponseSerializer(
    serializers.Serializer
):
    success = serializers.BooleanField()
    message = serializers.CharField()