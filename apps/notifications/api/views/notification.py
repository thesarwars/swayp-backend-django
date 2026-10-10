from drf_spectacular.utils import extend_schema

from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.common.swagger import (
    BAD_REQUEST_RESPONSE,
    NOT_FOUND_RESPONSE,
    UNAUTHORIZED_RESPONSE,
)
from apps.notifications.api.serializers.notification import (
    MarkNotificationReadResponseSerializer,
    NotificationListResponseSerializer,
    NotificationQuerySerializer,
    NotificationSerializer,
)
from apps.notifications.services import NotificationService


class NotificationListAPIView(BaseAPIView):

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
                "unreadCount": self.service.unread_count(user=request.user),
            },
        )


class NotificationReadAPIView(BaseAPIView):

    service_class = NotificationService

    @extend_schema(
        tags=["Notifications"],
        summary="Mark Notification As Read",
        description="Marks a notification as read.",
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
        self.service.mark_as_read(
            user=request.user,
            notification_id=notification_id,
        )

        return ApiResponse.success(
            message="Notification marked as read.",
        )


class NotificationReadAllAPIView(BaseAPIView):

    service_class = NotificationService

    @extend_schema(
        tags=["Notifications"],
        summary="Mark All Notifications As Read",
        description="Marks all unread notifications as read.",
        responses={
            200: MarkNotificationReadResponseSerializer,
            400: BAD_REQUEST_RESPONSE,
            401: UNAUTHORIZED_RESPONSE,
        },
    )
    def patch(self, request):
        self.service.mark_all_as_read(
            user=request.user,
        )

        return ApiResponse.success(
            message="All notifications marked as read.",
        )
