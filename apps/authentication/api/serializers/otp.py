from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.authentication.models import OTPPurpose

User = get_user_model()


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    purpose = serializers.ChoiceField(
        choices=OTPPurpose.choices
    )

    def validate(self, attrs):
        email = attrs["email"].lower().strip()

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "User does not exist."}
            )

        attrs["user"] = user

        return attrs
