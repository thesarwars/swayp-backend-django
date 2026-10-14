from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers

from apps.authentication.services.lockout_service import LockoutService
from apps.common.error_codes import (
    ACCOUNT_INACTIVE,
    ACCOUNT_LOCKED,
    ACCOUNT_NOT_VERIFIED,
    INVALID_CREDENTIALS,
)

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs["email"].lower().strip()
        password = attrs["password"]

        # Looked up before authenticate() so the lock can be checked without
        # touching the password at all — otherwise response timing would tell
        # an attacker a locked account from a wrong password.
        known = User.objects.filter(email=email).first()
        lockout = LockoutService()

        if lockout.is_locked(known):
            raise serializers.ValidationError(
                {
                    "detail": (
                        "Too many failed attempts. Try again in "
                        f"{lockout.minutes_remaining(known)} minute(s)."
                    )
                },
                code=ACCOUNT_LOCKED,
            )

        # The password is checked here rather than through authenticate():
        # Django's backend refuses an inactive user outright, and a signup is
        # inactive until its code is entered, so an unverified user with the
        # right password was told "Invalid email or password" and the two
        # branches below could never run (web C8).
        if known is not None:
            user = known if known.check_password(password) else None
        else:
            # Same hashing cost as a real check, so response time does not
            # say whether the address has an account.
            User().set_password(password)
            user = None

        if not user:
            # Counts against the known account when there is one, and does
            # nothing at all when there is not — creating or touching state
            # for an unknown email is how a lockout becomes a way to discover
            # who has an account.
            lockout.record_failure(known)

            raise serializers.ValidationError(
                {"detail": "Invalid email or password."},
                code=INVALID_CREDENTIALS,
            )

        # A correct password ends the sequence, even if the account was
        # inactive or unverified — those are different problems.
        lockout.record_success(user)

        # Not verified first: a signup that never entered its code is
        # also inactive, and "verify your email" is what it needs to hear.
        if not user.is_verified:
            raise serializers.ValidationError(
                {"detail": "Account is not verified."},
                code=ACCOUNT_NOT_VERIFIED,
            )

        if not user.is_active:
            raise serializers.ValidationError(
                {"detail": "Account is inactive."}, code=ACCOUNT_INACTIVE
            )

        attrs["user"] = user

        return attrs


# LoginVerifyOTPSerializer is gone. Its work is done by VerifyOTPSerializer in
# serializers/otp.py, which searches the login and registration codes together
# so the caller does not have to know which one it is holding.
