from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.api.serializers import RegisterSerializer
from apps.authentication.services.registration_service import RegistrationService


from apps.authentication.services.verify_otp_service import (
    VerifyOTPService,
)

from apps.authentication.services.resend_otp_service import (
    ResendOTPService,
)

from apps.authentication.api.serializers import (
    RegisterSerializer,
    VerifyOTPSerializer,
    ResendOTPSerializer,
    LoginSerializer,
    LoginVerifyOTPSerializer,
)



from apps.authentication.services.login_verify_service import (
    LoginVerifyService,
)

from apps.authentication.services.login_service import LoginService


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
    
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        LoginService.login(
            serializer.validated_data["user"]
        )

        return Response(
            {
                "success": True,
                "message": "OTP has been sent.",
            },
            status=status.HTTP_200_OK,
        )
    

class LoginVerifyOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginVerifyOTPSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        tokens = LoginVerifyService.verify(
            serializer.validated_data["user"],
            serializer.validated_data["otp_obj"],
            request,
        )

        return Response(
            {
                "success": True,
                "message": "Login successful.",
                "data": tokens,
            },
            status=status.HTTP_200_OK,
        )
    

class ResendOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResendOTPSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        ResendOTPService.resend(
            serializer.validated_data["user"],
            serializer.validated_data["purpose"],
        )

        return Response(
            {
                "success": True,
                "message": "OTP sent successfully.",
            },
            status=status.HTTP_200_OK,
        )