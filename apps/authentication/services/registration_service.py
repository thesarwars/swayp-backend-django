from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

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
        # The serializer no longer declares confirm_password, so there is
        # nothing here to discard — popping it would raise KeyError.
        # validated_data.pop("confirm_password")
        account_type = validated_data.pop("account_type", AccountType.BUSINESS)
        full_name = validated_data.pop("full_name")
        first_name = validated_data.pop("first_name", "")
        last_name = validated_data.pop("last_name", "")
        address = validated_data.pop("address", "")
        business_name = validated_data.pop("business_name", "")
        poc_name = validated_data.pop("poc_name", "")
        billing_address = validated_data.pop("billing_address", "")
        industry = validated_data.pop("industry", "")
        business_size = validated_data.pop("business_size", "")
        terms_accepted = validated_data.pop("terms_accepted", False)
        signatory_confirmed = validated_data.pop("signatory_confirmed", False)
        marketing_opt_in = validated_data.pop("marketing_opt_in", False)
        email = validated_data.pop("email")

        # None, never "". phone_number is unique and nullable: Postgres allows
        # many NULLs but only one empty string, so a blank here would let the
        # first phone-less signup succeed and collide every one after it.
        phone_number = validated_data.pop("phone_number", "") or None

        user = User.objects.create_user(
            email=email,
            phone_number=phone_number,
            password=password,
        )

        # Kept in step with the profile from the start, because the dashboard
        # greeting and the Stripe customer both read these.
        if first_name or last_name:
            user.first_name = first_name[:150]
            user.last_name = last_name[:150]
            user.save(update_fields=["first_name", "last_name"])

        # Seed password history so a later reset can't reuse this password.
        PasswordHistoryService().record(user=user)

        now = timezone.now()

        profile = Profile.objects.create(
            user=user,
            account_type=account_type,
            full_name=full_name,
            address=address,
            # Timestamped rather than boolean: "did they accept, and when"
            # has to be answerable later, and a flag answers only half of it.
            terms_accepted_at=now if terms_accepted else None,
            signatory_confirmed_at=now if signatory_confirmed else None,
            marketing_opt_in=marketing_opt_in,
        )

        if account_type == AccountType.BUSINESS:
            BusinessProfile.objects.create(
                profile=profile,
                business_name=business_name,
                poc_name=poc_name,
                billing_address=billing_address,
                industry=industry,
                business_size=business_size,
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