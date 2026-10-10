from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.casing import with_snake_case
from apps.common.responses import ApiResponse
from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    NOT_FOUND_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)
from apps.notifications.api.serializers.notification import (
    MarkAllReadResponseSerializer,
    MarkNotificationReadResponseSerializer,
    NotificationListResponseSerializer,
    NotificationQuerySerializer,
    NotificationSerializer,
)
from apps.notifications.services import NotificationService


class NotificationListAPIView(BaseAPIView):

    # pagination beside data in the schema (apps/common/schema.py).
    paginated_response = True

    service_class = NotificationService

    @extend_schema(
        tags=["Notifications"],
        summary="List Notifications",
        description=(
            "Returns notifications for the authenticated user. `type` "
            "(repeatable), `category` and `isRead` narrow the list before "
            "pagination, so totals and pages describe the filtered set. "
            "`type` and `category` together return their intersection."
        ),
        parameters=[NotificationQuerySerializer],
        responses={
            200: NotificationListResponseSerializer,
            400: BAD_REQUEST_RESPONSE,
            401: UNAUTHORIZED_RESPONSE,
        },
    )
    def get(self, request):
        query = NotificationQuerySerializer(
            data=request.query_params,
        )

        query.is_valid(raise_exception=True)

        result = self.service.list_notifications(
            user=request.user,
            page=query.validated_data["page"],
            page_size=query.validated_data["pageSize"],
            types=query.validated_data.get("type"),
            category=query.validated_data.get("category"),
            is_read=query.validated_data.get("isRead"),
            before=query.validated_data.get("before"),
        )

        serializer = NotificationSerializer(
            result["items"],
            many=True,
        )

        return ApiResponse.success(
            data=serializer.data,
            pagination=result["pagination"],
            # Unfiltered: the bell badge counts every unread notification,
            # whatever chip the list is showing (DASH-4).
            extra={
                "nextCursor": result["next_cursor"],
                "unreadCount": self.service.unread_count(user=request.user),
            },
        )


class NotificationReadAPIView(BaseAPIView):

    service_class = NotificationService

    @extend_schema(
        tags=["Notifications"],
        summary="Mark Notification As Read",
        description=(
            "Marks one of the caller's notifications as read and returns it, "
            "with the unread count after the change. Idempotent: an "
            "already-read notification answers 200 with its original readAt. "
            "Another person's id, or an unknown one, is 404."
        ),
        responses={
            200: MarkNotificationReadResponseSerializer,
            400: BAD_REQUEST_RESPONSE,
            401: UNAUTHORIZED_RESPONSE,
            404: NOT_FOUND_RESPONSE,
        },
    )
    def patch(
        self,
        request,
        notification_id,
    ):
        notification = self.service.mark_as_read(
            user=request.user,
            notification_id=notification_id,
        )

        return ApiResponse.success(
            data=NotificationSerializer(notification).data,
            message="Notification marked as read.",
            extra={
                "unreadCount": self.service.unread_count(user=request.user),
            },
        )


class NotificationReadAllAPIView(BaseAPIView):

    service_class = NotificationService

    @extend_schema(
        tags=["Notifications"],
        summary="Mark All Notifications As Read",
        description=(
            "Marks all of the caller's unread notifications as read. "
            "data.markedCount is how many changed (0 when none were unread); "
            "unreadCount is then 0."
        ),
        responses={
            200: MarkAllReadResponseSerializer,
            400: BAD_REQUEST_RESPONSE,
            401: UNAUTHORIZED_RESPONSE,
        },
    )
    def patch(self, request):
        marked = self.service.mark_all_as_read(
            user=request.user,
        )

        return ApiResponse.success(
            data=with_snake_case({"markedCount": marked}),
            message="All notifications marked as read.",
            extra={
                "unreadCount": self.service.unread_count(user=request.user),
            },
        )
