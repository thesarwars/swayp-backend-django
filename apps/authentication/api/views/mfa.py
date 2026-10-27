"""Two-step verification endpoints (see services/mfa_service.py)."""

from drf_spectacular.utils import extend_schema

from apps.authentication.api.serializers.mfa import (
    MFAAppCodeSerializer,
    MFACodeSerializer,
    MFADisableSerializer,
    MFALoginResponseSerializer,
    MFALoginSerializer,
    MFASetupSerializer,
    MFAStatusSerializer,
    RecoveryCodesSerializer,
)
from apps.authentication.api.views.sessions import current_sid
from apps.authentication.services.mfa_service import MFAChallenge, MFAService
from apps.authentication.throttles import MFARateThrottle
from apps.common.base_views import BaseAPIView, PublicAPIView
from apps.common.responses import ApiResponse


@extend_schema(
    tags=["Authentication"],
    summary="Two-step verification status",
    responses={200: MFAStatusSerializer},
)
class MFAStatusAPIView(BaseAPIView):

    def get(self, request):
        return ApiResponse.success(
            data=MFAStatusSerializer(MFAService.status(request.user)).data,
            message="Two-step verification status.",
        )


@extend_schema(
    tags=["Authentication"],
    summary="Start two-step verification setup",
    description=(
        "A new secret for the authenticator app: show otpauth_uri as a QR "
        "code, with secret for typing in by hand. Nothing changes until "
        "mfa/confirm. Calling again restarts setup. 400 mfa_already_enabled "
        "while it is on."
    ),
    request=None,
    responses={200: MFASetupSerializer},
)
class MFASetupAPIView(BaseAPIView):

    def post(self, request):
        return ApiResponse.success(
            data=MFAService.setup(request.user),
            message="Scan the code with your authenticator app.",
        )


@extend_schema(
    tags=["Authentication"],
    summary="Finish two-step verification setup",
    description=(
        "A code from the app turns it on. The answer holds 10 recovery "
        "codes, shown this once: ask the user to save them. 400 "
        "mfa_code_invalid for a wrong code."
    ),
    request=MFAAppCodeSerializer,
    responses={200: RecoveryCodesSerializer},
)
class MFAConfirmAPIView(BaseAPIView):

    throttle_classes = [MFARateThrottle]

    def post(self, request):
        serializer = MFAAppCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        codes = MFAService.confirm(
            request.user, serializer.validated_data["code"]
        )

        return ApiResponse.success(
            data={"recovery_codes": codes},
            message="Two-step verification is on.",
        )


@extend_schema(
    tags=["Authentication"],
    summary="Turn two-step verification off",
    description=(
        "Needs a current code (app or recovery) and the password, unless the "
        "account signs in with Google only. Every other session is signed "
        "out and the user is emailed."
    ),
    request=MFADisableSerializer,
    responses={200: None},
)
class MFADisableAPIView(BaseAPIView):

    throttle_classes = [MFARateThrottle]
    nullable_data = ("POST",)

    def post(self, request):
        serializer = MFADisableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        MFAService.disable(
            request.user,
            code=serializer.validated_data["code"],
            password=serializer.validated_data.get("password"),
            keep_session=current_sid(request),
        )

        return ApiResponse.success(
            data=None, message="Two-step verification is off."
        )


@extend_schema(
    tags=["Authentication"],
    summary="New recovery codes",
    description=(
        "Replaces every recovery code, used or not, with 10 new ones shown "
        "this once. Needs a code from the app."
    ),
    request=MFAAppCodeSerializer,
    responses={200: RecoveryCodesSerializer},
)
class MFARecoveryCodesAPIView(BaseAPIView):

    throttle_classes = [MFARateThrottle]

    def post(self, request):
        serializer = MFAAppCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        codes = MFAService.regenerate_recovery_codes(
            request.user, serializer.validated_data["code"]
        )

        return ApiResponse.success(
            data={"recovery_codes": codes},
            message="New recovery codes made. The old ones no longer work.",
        )


@extend_schema(
    tags=["Authentication"],
    summary="Finish a sign-in with a two-step code",
    description=(
        "After any sign-in that answered mfa_required: true. Send its "
        "mfa_token with a code from the app or a recovery code. The token "
        "lasts 5 minutes and 5 wrong codes; after that, 400 "
        "mfa_challenge_invalid means sign in again."
    ),
    request=MFALoginSerializer,
    responses={200: MFALoginResponseSerializer},
)
class MFALoginAPIView(PublicAPIView):

    throttle_classes = [MFARateThrottle]

    def post(self, request):
        serializer = MFALoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tokens = MFAChallenge.complete(
            serializer.validated_data["mfa_token"],
            serializer.validated_data["code"],
            request,
        )

        return ApiResponse.success(data=tokens, message="Login successful.")
