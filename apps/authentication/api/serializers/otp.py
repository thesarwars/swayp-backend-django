from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.authentication.models import OTPChannel, OTPPurpose

User = get_user_model()


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    purpose = serializers.ChoiceField(
        choices=OTPPurpose.choices
    )

    # Accepted so the SMS screens can be built, but validated to EMAIL by the
    # service — SMS is deferred this release (E2-S1).
    channel = serializers.ChoiceField(
        choices=OTPChannel.choices,
        required=False,
        default=OTPChannel.EMAIL,
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
