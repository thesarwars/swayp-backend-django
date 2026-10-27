from drf_spectacular.utils import extend_schema

from apps.authentication.api.serializers.sessions import (
    RevokeAllSessionsResponseSerializer,
    RevokeAllSessionsSerializer,
    SessionSerializer,
)
from apps.authentication.services.session_service import (
    SID_CLAIM,
    SessionService,
)
from apps.common.base_views import BaseAPIView
from apps.common.exceptions import NotFoundException
from apps.common.responses import ApiResponse


def current_sid(request):
    """The session id the caller's access token belongs to, or None for a
    token minted before sessions carried one."""
    token = request.auth

    return str(token.get(SID_CLAIM)) if token and token.get(SID_CLAIM) else None


@extend_schema(
    tags=["Authentication"],
    summary="Where you're signed in",
    description=(
        "Every live session of the caller's, most recently used first. "
        "current marks this device. user_agent is the raw header for the "
        "client to render as a device name."
    ),
    responses={200: SessionSerializer(many=True)},
)
class SessionListAPIView(BaseAPIView):

    def get(self, request):
        sessions = SessionService.active(request.user)

        return ApiResponse.success(
            data=SessionSerializer(
                sessions,
                many=True,
                context={"current_sid": current_sid(request)},
            ).data,
            message="Sessions fetched successfully.",
        )


@extend_schema(
    tags=["Authentication"],
    summary="Sign out one session",
    description=(
        "Ends it at once: its refresh token is refused and so is its access "
        "token, on the next request. Ending the current session is a "
        "logout. 404 for a session that is not the caller's or already "
        "ended."
    ),
    responses={200: None},
)
class SessionDetailAPIView(BaseAPIView):

    nullable_data = ("DELETE",)

    def delete(self, request, session_id):
        if not SessionService.end(request.user, session_id):
            raise NotFoundException("Session not found.")

        return ApiResponse.success(data=None, message="Session signed out.")


@extend_schema(
    tags=["Authentication"],
    summary="Sign out everywhere",
    description=(
        "Ends every session except this one, unless include_current is "
        "true. Takes effect at once on every device."
    ),
    request=RevokeAllSessionsSerializer,
    responses={200: RevokeAllSessionsResponseSerializer},
)
class SessionRevokeAllAPIView(BaseAPIView):

    def post(self, request):
        serializer = RevokeAllSessionsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        keep = (
            None
            if serializer.validated_data["include_current"]
            else current_sid(request)
        )
        revoked = SessionService.end_all(request.user, keep=keep)

        return ApiResponse.success(
            data={"revoked": revoked},
            message="Signed out everywhere else."
            if keep
            else "Signed out everywhere.",
        )
