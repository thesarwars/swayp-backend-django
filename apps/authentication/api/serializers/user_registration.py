import re

from django.contrib.auth import get_user_model
from django.utils import timezone
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

from apps.authentication.models import OTP, OTPPurpose
from apps.authentication.utils.otp import OTPService

from apps.users.models import AccountType

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    """Registration, reconciled with the Create Account screen.

    The screen asks for first name, last name, business email, business name,
    industry, business size, a password and three checkboxes — and nothing
    else. It does not ask for a postal address, a phone number, a billing
    address or a point of contact, all of which this endpoint used to demand,
    so a client built to the design could not register at all.

    Those four are optional now. They are not lost: onboarding Step 1 and the
    settings screen collect them, and PATCH /users/profile/ persists them.
    Asking for a billing address before the customer has chosen a plan was
    always the wrong order.

    In the other direction the screen sends fields this endpoint had nowhere
    to put: a split name, industry and business size. All three are accepted.
    ``full_name`` still works, so existing clients are unaffected.
    """

    # "Business accounts only" per the screen, but INDIVIDUAL stays reachable
    # for the phone-signup path, so this defaults rather than narrows.
    account_type = serializers.ChoiceField(
        choices=AccountType.choices,
        required=False,
        default=AccountType.BUSINESS,
    )

    # The screen splits the name; older clients send it whole. Either works,
    # and validate() reconciles them.
    full_name = serializers.CharField(max_length=255, required=False)
    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)

    email = serializers.EmailField()

    # Optional: the screen has no field for these. A missing phone means no
    # phone login until one is added in settings, which is the honest
    # consequence rather than a blocked signup.
    address = serializers.CharField(required=False, allow_blank=True)
    phone_number = PhoneNumberField(required=False, allow_blank=True)
    billing_address = serializers.CharField(
        required=False, allow_blank=True
    )
    poc_name = serializers.CharField(required=False, allow_blank=True)

    business_name = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    # On the Create Account screen as dropdowns. Free text, because the
    # option lists are not specified anywhere and an invented enum would
    # reject whatever the real list turns out to be.
    industry = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    business_size = serializers.CharField(
        max_length=50, required=False, allow_blank=True
    )

    password = serializers.CharField(
        write_only=True,
        # min_length=12,
        style={"input_type": "password"},
    )

    # confirm_password = serializers.CharField(
    #     write_only=True,
    #     style={"input_type": "password"},
    # )

    # The screen's three checkboxes. The first two are ticked to proceed and
    # are legal artifacts, so they are recorded with a timestamp; the third is
    # a preference. Defaulting the consents to False keeps older clients
    # working while still recording the truth: they did not tick anything.
    terms_accepted = serializers.BooleanField(required=False, default=False)
    signatory_confirmed = serializers.BooleanField(
        required=False, default=False
    )
    marketing_opt_in = serializers.BooleanField(
        required=False, default=False
    )

    def validate_email(self, value):
        value = value.lower().strip()

        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "Email already exists."
            )

        return value

    def validate_phone_number(self, value):
        if not value:
            return value

        if User.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError(
                "Phone number already exists."
            )

        return value

    def validate_password(self, value):

        # if len(value) < 12:
        #     raise serializers.ValidationError(
        #         "Password must contain at least 12 characters."
        #     )

        if not re.search(r"[A-Z]", value):
            raise serializers.ValidationError(
                "Password must contain one uppercase letter."
            )

        if not re.search(r"[a-z]", value):
            raise serializers.ValidationError(
                "Password must contain one lowercase letter."
            )

        if not re.search(r"[0-9]", value):
            raise serializers.ValidationError(
                "Password must contain one digit."
            )

        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", value):
            raise serializers.ValidationError(
                "Password must contain one special character."
            )

        return value

    def validate(self, attrs):

        # if attrs["password"] != attrs["confirm_password"]:
        #     raise serializers.ValidationError(
        #         {
        #             "confirm_password": "Passwords do not match."
        #         }
        #     )

        # The screen sends first/last; older clients send full_name. Build
        # whichever is missing so everything downstream sees both.
        full_name = (attrs.get("full_name") or "").strip()
        first = (attrs.get("first_name") or "").strip()
        last = (attrs.get("last_name") or "").strip()

        if not full_name:
            full_name = " ".join(part for part in (first, last) if part)

        if not full_name:
            raise serializers.ValidationError(
                {
                    "full_name": (
                        "Provide full_name, or first_name and last_name."
                    )
                }
            )

        attrs["full_name"] = full_name

        if not first:
            parts = full_name.split(" ", 1)
            attrs["first_name"] = parts[0]
            attrs["last_name"] = parts[1] if len(parts) > 1 else ""

        account_type = attrs.get("account_type", AccountType.BUSINESS)

        if account_type == AccountType.BUSINESS:

            if not attrs.get("business_name"):
                raise serializers.ValidationError(
                    {
                        "business_name": "This field is required."
                    }
                )

            # poc_name is no longer required. It is not on the Create Account
            # screen, and defaulting it to the person signing up is both true
            # and better than refusing the signup. Settings can change it.
            if not attrs.get("poc_name"):
                attrs["poc_name"] = full_name

        return attrs


class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(
        min_length=6,
        max_length=6,
    )

    def validate(self, attrs):
        email = attrs["email"].lower()

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "User does not exist."}
            )

        otp_obj = (
            OTP.objects.filter(
                user=user,
                purpose=OTPPurpose.REGISTRATION,
                used_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )

        if not otp_obj:
            raise serializers.ValidationError(
                {"otp": "OTP not found."}
            )

        if otp_obj.expires_at < timezone.now():
            raise serializers.ValidationError(
                {"otp": "OTP expired."}
            )

        if not OTPService.verify_otp(
            attrs["otp"],
            otp_obj.code_hash,
        ):
            otp_obj.attempts += 1
            otp_obj.save(update_fields=["attempts"])
            raise serializers.ValidationError(
                {"otp": "Invalid OTP."}
            )

        attrs["user"] = user
        attrs["otp_obj"] = otp_obj

        return attrs
