from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers


class PhoneChangeRequestSerializer(serializers.Serializer):
    """The number the account wants. Parsed the same way as at registration,
    so both paths store one E.164 spelling and phone sign-in finds either."""

    phone_number = PhoneNumberField()

    def validate_phone_number(self, value):
        return str(value)


class PhoneChangeVerifySerializer(PhoneChangeRequestSerializer):
    otp = serializers.CharField(min_length=6, max_length=6)


class PhoneChangeRequestResponseSerializer(serializers.Serializer):
    email = serializers.CharField(help_text="Masked address the code went to.")
