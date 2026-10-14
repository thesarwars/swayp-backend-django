from drf_spectacular.utils import extend_schema

from apps.authentication.api.serializers.token import TokenPairSerializer
from apps.common.base_views import BaseAPIView
from apps.common.responses import ApiResponse
from apps.users.api.serializers.password import ChangePasswordSerializer
from apps.users.services.password_service import ChangePasswordService


@extend_schema(
    tags=["Users"],
    summary="Change password",
    description=(
        "For a signed-in user. current_password must be right (400 "
        "invalid_credentials otherwise); new_password follows the "
        "registration rules and may not repeat the previous one. Every "
        "other session is signed out, and the answer is a fresh token pair "
        "for this device: store it."
    ),
    request=ChangePasswordSerializer,
    responses={200: TokenPairSerializer},
)
class ChangePasswordAPIView(BaseAPIView):

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        tokens = ChangePasswordService.change(
            user=request.user,
            new_password=serializer.validated_data["new_password"],
            request=request,
        )

        return ApiResponse.success(data=tokens, message="Password changed.")
