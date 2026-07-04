from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.api.serializers import RegisterSerializer, ResetPasswordSerializer
from apps.authentication.services.registration_service import RegistrationService


from apps.authentication.services.reset_password_service import ResetPasswordService
from apps.authentication.services.verify_otp_service import (
    VerifyOTPService,
)
from apps.authentication.services.logout_service import (
    LogoutService,
)

from apps.authentication.services.resend_otp_service import (
    ResendOTPService,
)

from rest_framework_simplejwt.views import TokenRefreshView

from apps.authentication.api.serializers import (
    RegisterSerializer,
    VerifyOTPSerializer,
    ResendOTPSerializer,
    LoginSerializer,
    LoginVerifyOTPSerializer,
    RefreshSerializer,
    LogoutSerializer,
    ForgotPasswordSerializer,
)

from drf_spectacular.utils import (
    OpenApiExample,
    extend_schema,
    OpenApiResponse,
)

from apps.authentication.services.refresh_token_service import (
    RefreshTokenService,
)
from apps.authentication.services.forgot_password_service import (
    ForgotPasswordService,
)



from apps.authentication.services.login_verify_service import (
    LoginVerifyService,
)

from apps.authentication.services.login_service import LoginService




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



@extend_schema(
    tags=["Authentication"],
    summary="Login",
    description="Validate credentials and send login OTP.",
    request=LoginSerializer,
    responses={
        200: OpenApiResponse(description="OTP sent."),
        400: OpenApiResponse(description="Invalid credentials."),
    },
    examples=[
        OpenApiExample(
            "Login",
            value={
                "email": "john@gmail.com",
                "password": "Password@123",
            },
            request_only=True,
        )
    ],
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
    




@extend_schema(
    tags=["Authentication"],
    summary="Verify Login OTP",
    description="Verify login OTP and return JWT tokens.",
    request=LoginVerifyOTPSerializer,
    responses={
        200: OpenApiResponse(description="Login successful."),
        400: OpenApiResponse(description="Invalid OTP."),
    },
    examples=[
        OpenApiExample(
            "Verify Login OTP",
            value={
                "email": "john@gmail.com",
                "otp": "123456",
            },
            request_only=True,
        )
    ],
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
    


@extend_schema(
    tags=["Authentication"],
    summary="Resend OTP",
    description="Generate and resend OTP.",
    request=ResendOTPSerializer,
    responses={
        200: OpenApiResponse(description="OTP sent."),
    },
    examples=[
        OpenApiExample(
            "Resend OTP",
            value={
                "email": "john@gmail.com",
                "purpose": "LOGIN",
            },
            request_only=True,
        )
    ],
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
    




@extend_schema(
    tags=["Authentication"],
    summary="Refresh Access Token",
    description="Generate a new access token using a refresh token.",
    request=RefreshSerializer,
    responses={
        200: OpenApiResponse(description="Token refreshed."),
    },
    examples=[
        OpenApiExample(
            "Refresh Token",
            value={
                "refresh": "your_refresh_token",
            },
            request_only=True,
        )
    ],
)

class RefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RefreshSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        tokens = RefreshTokenService.refresh(
            serializer.validated_data["refresh"]
        )

        return Response(
            {
                "success": True,
                "data": tokens,
            }
        )
    

@extend_schema(
    tags=["Authentication"],
    summary="Logout",
    description="Logout current session.",
    request=LogoutSerializer,
    responses={
        204: OpenApiResponse(description="Logged out."),
    },
    examples=[
        OpenApiExample(
            "Logout",
            value={
                "refresh": "your_refresh_token",
            },
            request_only=True,
        )
    ],
)
class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LogoutSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        LogoutService.logout(
            serializer.validated_data["refresh"]
        )

        return Response(
            status=status.HTTP_204_NO_CONTENT
        )
    



@extend_schema(
    tags=["Authentication"],
    summary="Forgot Password",
    description="Send password reset OTP.",
    request=ForgotPasswordSerializer,
    responses={
        200: OpenApiResponse(description="OTP sent."),
    },
    examples=[
        OpenApiExample(
            "Forgot Password",
            value={
                "email": "john@gmail.com",
            },
            request_only=True,
        )
    ],
)
    
class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        ForgotPasswordService.send(
            serializer.user
        )

        return Response(
            {
                "success": True,
                "message": "OTP sent successfully.",
            }
        )



@extend_schema(
    tags=["Authentication"],
    summary="Reset Password",
    description="Reset account password using OTP.",
    request=ResetPasswordSerializer,
    responses={
        200: OpenApiResponse(description="Password reset successful."),
    },
    examples=[
        OpenApiExample(
            "Reset Password",
            value={
                "email": "john@gmail.com",
                "otp": "123456",
                "password": "NewPassword@123",
                "confirm_password": "NewPassword@123",
            },
            request_only=True,
        )
    ],
)

class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        ResetPasswordService.reset(
            email=serializer.validated_data["email"],
            otp=serializer.validated_data["otp"],
            password=serializer.validated_data["password"],
        )

        return Response(
            {
                "success": True,
                "message": "Password reset successful.",
            }
        )