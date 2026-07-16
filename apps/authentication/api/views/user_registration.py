from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.api.serializers.user_registration import (
    RegisterSerializer,
    VerifyOTPSerializer,
)
from apps.authentication.services.registration_service import (
    RegistrationService,
)
from apps.authentication.services.verify_otp_service import (
    VerifyOTPService,
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
                "confirm_password": "Password@123",
                "business_name": "ABC Ltd",
                "poc_name": "John Doe",
                "billing_address": "Dhaka",
            },
        )
    ],
)
class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        RegistrationService.register(serializer.validated_data)

        return Response(
            {
                "success": True,
                "message": "Registration successful. OTP has been sent.",
            },
            status=status.HTTP_201_CREATED,
        )


@extend_schema(
    tags=["Authentication"],
    summary="Verify Registration OTP",
    description="Verify the OTP sent after registration.",
    request=VerifyOTPSerializer,
    responses={
        200: OpenApiResponse(description="Account verified."),
        400: OpenApiResponse(description="Invalid OTP."),
    },
    examples=[
        OpenApiExample(
            "Verify Registration OTP",
            value={
                "email": "john@gmail.com",
                "otp": "123456",
            },
            request_only=True,
        )
    ],
)
class VerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tokens = VerifyOTPService.verify(
            serializer.validated_data["user"],
            serializer.validated_data["otp_obj"],
        )

        return Response(
            {
                "success": True,
                "message": "Account verified successfully.",
                "data": tokens,
            },
            status=status.HTTP_200_OK,
        )
