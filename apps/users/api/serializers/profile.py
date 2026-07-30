from rest_framework import serializers

from apps.users.models.profile import AccountType


class ProfileSerializer(serializers.Serializer):
    """The account's own profile, read.

    account_type, email, phone_number and is_verified are read-only: the first
    changes what the account *is*, and the other three are login identifiers
    verified by OTP, so changing one is an authentication flow rather than a
    profile edit.
    """

    account_type = serializers.ChoiceField(
        choices=AccountType.choices, read_only=True
    )
    email = serializers.EmailField(read_only=True)
    phone_number = serializers.CharField(read_only=True)
    is_verified = serializers.BooleanField(read_only=True)

    full_name = serializers.CharField()
    address = serializers.CharField(allow_blank=True)
    billing_address = serializers.CharField(allow_blank=True)

    # Null for an individual account. Present either way so a client can
    # render one form without branching on whether the key exists.
    business_name = serializers.CharField(allow_null=True)
    poc_name = serializers.CharField(allow_null=True)


class ProfileUpdateSerializer(serializers.Serializer):
    """Partial update. Every field optional — this backs a settings screen
    where somebody fixes one typo, not a form that resubmits everything."""

    full_name = serializers.CharField(
        max_length=255, required=False, allow_blank=False
    )
    address = serializers.CharField(required=False, allow_blank=True)
    billing_address = serializers.CharField(
        required=False, allow_blank=True
    )
    business_name = serializers.CharField(
        max_length=255, required=False, allow_blank=False
    )
    poc_name = serializers.CharField(
        max_length=255, required=False, allow_blank=False
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Send at least one field to update."
            )

        return attrs
