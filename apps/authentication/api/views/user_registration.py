from drf_spectacular.utils import (
    OpenApiExample,
    extend_schema,
)
from rest_framework import status
from rest_framework.response import Response
from apps.common.base_views import PublicAPIView
from apps.common.crypto import mask_email

from apps.authentication.api.serializers.user_registration import (
    MaskedEmailSerializer,
    RegisterSerializer,
)
from apps.authentication.throttles import RegisterRateThrottle
from apps.authentication.services.registration_service import (
    RegistrationService,
)


@extend_schema(
    tags=["Authentication"],
    request=RegisterSerializer,
    responses={201: MaskedEmailSerializer},
    summary="Register",
    description=(
        "Creates the account and emails a REGISTRATION code; finish with "
        "verify-otp. data.email is masked for the 'check your inbox' screen."
    ),
    examples=[
        # What the Create Account screen sends. The phone number is added
        # later from Settings; full_name is derived from first and last.
        OpenApiExample(
            "Business",
            value={
                "first_name": "Jane",
                "last_name": "Smith",
                "email": "jane@acme.com",
                "business_name": "Acme Corporation, LLC",
                "industry": "Construction",
                "business_size": "11-50",
                "password": "Str0ng!Passphrase1",
                "terms_accepted": True,
                "signatory_confirmed": True,
                "marketing_opt_in": False,
            },
            request_only=True,
        ),
        OpenApiExample(
            "Individual",
            value={
                "account_type": "INDIVIDUAL",
                "first_name": "Jane",
                "last_name": "Smith",
                "email": "jane@example.com",
                "password": "Str0ng!Passphrase1",
                "terms_accepted": True,
            },
            request_only=True,
        ),
    ],
)


class RegisterView(PublicAPIView):

    throttle_classes = [RegisterRateThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = RegistrationService.register(serializer.validated_data)

        # Masked, and carried in ``data`` as well as the sentence: the screen
        # needs the address to render "check x***e@gmail.com" without parsing
        # English, and a client that echoes a full address back onto a shared
        # screen leaks it to whoever is looking.
        email = mask_email(user.email)

        return Response(
            {
                "success": True,
                "message": (
                    f"Registration successful. OTP has been sent to {email}."
                ),
                "data": {"email": email},
            },
            status=status.HTTP_201_CREATED,
        )


# VerifyOTPView moved to views/otp.py, where it answers for the login code as
# well. VerifyOTPService is still what finishes a registration; the merged view
# dispatches to it on the matched code's purpose.
