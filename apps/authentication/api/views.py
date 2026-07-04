from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authentication.api.serializers import RegisterSerializer
from apps.authentication.services.registration_service import RegistrationService


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