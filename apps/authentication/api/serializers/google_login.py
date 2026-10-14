from rest_framework import serializers

from apps.users.models import AccountType


class GoogleLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField(
        help_text="The ID token from Google Sign-In on the device."
    )
    # Used only when the account is created. Ignored for an existing one.
    account_type = serializers.ChoiceField(
        choices=AccountType.choices,
        default=AccountType.BUSINESS,
        required=False,
    )
    terms_accepted = serializers.BooleanField(required=False, default=False)
    # As on the register form (web §4): the person confirms they may act
    # for the business. Recorded with a timestamp when the account is new.
    signatory_confirmed = serializers.BooleanField(
        required=False, default=False
    )
    marketing_opt_in = serializers.BooleanField(required=False, default=False)


class GoogleLoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    is_new_user = serializers.BooleanField(
        help_text="True when this sign-in created the account: send them "
        "to onboarding."
    )
