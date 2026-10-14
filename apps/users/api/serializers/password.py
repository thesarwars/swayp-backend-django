from rest_framework import serializers

from apps.authentication.utils.passwords import password_problem
from apps.common.error_codes import INVALID_CREDENTIALS


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        user = self.context["request"].user

        if not user.check_password(value):
            raise serializers.ValidationError(
                "Current password is incorrect.", code=INVALID_CREDENTIALS
            )

        return value

    def validate_new_password(self, value):
        problem = password_problem(value)

        if problem:
            raise serializers.ValidationError(problem)

        return value
