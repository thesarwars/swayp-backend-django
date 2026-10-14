from drf_spectacular.utils import OpenApiResponse, extend_schema

from apps.authentication.api.serializers.google_login import (
    GoogleLoginResponseSerializer,
    GoogleLoginSerializer,
)
from apps.authentication.services.google_identity_service import (
    GoogleIdentityService,
)
from apps.authentication.services.google_login_service import (
    GoogleLoginService,
)
from apps.common.base_views import PublicAPIView
from apps.common.responses import ApiResponse


@extend_schema(
    tags=["Authentication"],
    summary="Sign in with Google",
    description=(
        "Exchanges a Google ID token for access/refresh tokens. Signs in the "
        "account with that Google identity or email, or creates one "
        "(is_new_user: true) with the email already verified. account_type, "
        "terms_accepted and marketing_opt_in apply only on creation."
    ),
    request=GoogleLoginSerializer,
    responses={
        200: GoogleLoginResponseSerializer,
        400: OpenApiResponse(description="Token invalid, or email unverified."),
        503: OpenApiResponse(description="Google sign-in not configured."),
    },
)
class GoogleLoginView(PublicAPIView):

    def post(self, request):
        serializer = GoogleLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        claims = GoogleIdentityService().verify(data["id_token"])

        result = GoogleLoginService.login(
            claims=claims,
            request=request,
            account_type=data["account_type"],
            terms_accepted=data["terms_accepted"],
            signatory_confirmed=data["signatory_confirmed"],
            marketing_opt_in=data["marketing_opt_in"],
        )

        return ApiResponse.success(
            data=result,
            message=(
                "Account created." if result["is_new_user"]
                else "Login successful."
            ),
        )
