from drf_spectacular.utils import (
    OpenApiExample,
    extend_schema,
)
from rest_framework import status
from rest_framework.response import Response
from apps.common.base_views import PublicAPIView
from apps.common.crypto import mask_email

from apps.authentication.api.serializers.user_registration import (
    RegisterSerializer,
)
from apps.authentication.services.registration_service import (
    RegistrationService,
)


@extend_schema(
    tags=["Authentication"],
    request=RegisterSerializer,
    responses={201: None},
    description="Register a new user.",
    examples=[
        OpenApiExample(
            "Business",
            value={
                "account_type": "BUSINESS",
                "full_name": "John Doe",
                "address": "Dhaka",
                "email": "john@gmail.com",
                "phone_number": "+8801712345678",
                "password": "Password@123",
                # "confirm_password": "Password@123",
                "business_name": "ABC Ltd",
                "poc_name": "John Doe",
                "billing_address": "Dhaka",
            },
        )
    ],
)


class RegisterView(PublicAPIView):

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
