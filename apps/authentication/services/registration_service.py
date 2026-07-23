from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.services.email_services import EmailService
from apps.authentication.utils.otp import OTPService
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

        otp = OTPService.generate_otp()

        OTP.objects.create(
            user=user,
            code_hash=OTPService.hash_otp(otp),
            purpose=OTPPurpose.REGISTRATION,
            expires_at=timezone.now() + timedelta(minutes=5),
        )

        try:
            EmailService.send_registration_otp(email, otp)
        except Exception:
            print(f"Registration OTP: {otp}")

        return user