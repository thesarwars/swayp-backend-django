from django.contrib.auth import get_user_model
from django.db import transaction

from apps.authentication.models import OTPPurpose
from apps.authentication.services.otp_delivery_service import (
    OTPDeliveryService,
)
from apps.authentication.services.password_history_service import (
    PasswordHistoryService,
)
from apps.users.models import (
    AccountType,
    BusinessProfile,
    IndividualProfile,
    Profile,
)

User = get_user_model()


class RegistrationService:

    @staticmethod
    @transaction.atomic
    def register(validated_data: dict):

        password = validated_data.pop("password")
        validated_data.pop("confirm_password")
        account_type = validated_data.pop("account_type")
        full_name = validated_data.pop("full_name")
        address = validated_data.pop("address")
        business_name = validated_data.pop("business_name", "")
        poc_name = validated_data.pop("poc_name", "")
        billing_address = validated_data.pop("billing_address")
        email = validated_data.pop("email")
        phone_number = validated_data.pop("phone_number")
        user = User.objects.create_user(
            email=email,
            phone_number=phone_number,
            password=password,
        )

        # Seed password history so a later reset can't reuse this password.
        PasswordHistoryService().record(user=user)

        profile = Profile.objects.create(
            user=user,
            account_type=account_type,
            full_name=full_name,
            address=address,
        )

        if account_type == AccountType.BUSINESS:
            BusinessProfile.objects.create(
                profile=profile,
                business_name=business_name,
                poc_name=poc_name,
                billing_address=billing_address,
            )
        else:
            IndividualProfile.objects.create(
                profile=profile,
                billing_address=billing_address,
            )

        OTPDeliveryService().issue(
            user=user,
            purpose=OTPPurpose.REGISTRATION,
        )

        return user