from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.authentication.models import OTP, OTPChannel, OTPPurpose
from apps.authentication.utils.otp import OTPService

User = get_user_model()

#: What ``/auth/verify-otp`` can complete. RESET_PASSWORD is deliberately not
#: one of them: that code is spent by ``/auth/reset-password`` together with the
#: new password, so consuming it here would leave the user holding a used code
#: and no way to finish.
VERIFIABLE_PURPOSES = (OTPPurpose.REGISTRATION, OTPPurpose.LOGIN)


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


class VerifyOTPSerializer(serializers.Serializer):
    """One serializer for the registration code and the login code.

    Two endpoints for the same six digits was a trap. The code arrives by
    email with nothing on it saying which flow issued it, so posting a login
    code to the registration endpoint answered "OTP not found." — which reads
    as "your code is wrong" when it meant "wrong door".

    ``purpose`` is optional. Left out, the submitted code is checked against
    every code the account has pending and whichever one matches decides the
    flow, so the caller never has to know. Sent, it narrows the search.
    """

    email = serializers.EmailField()

    otp = serializers.CharField(
        min_length=6,
        max_length=6,
    )

    purpose = serializers.ChoiceField(
        choices=[
            (purpose.value, purpose.label)
            for purpose in VERIFIABLE_PURPOSES
        ],
        required=False,
    )

    def validate(self, attrs):
        email = attrs["email"].lower().strip()

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {"email": "User does not exist."}
            )

        purposes = (
            [attrs["purpose"]]
            if attrs.get("purpose")
            else list(VERIFIABLE_PURPOSES)
        )

        pending = list(
            OTP.objects.filter(
                user=user,
                purpose__in=purposes,
                used_at__isnull=True,
            ).order_by("-created_at")
        )

        if not pending:
            raise serializers.ValidationError(
                {"otp": self._nothing_pending(user)}
            )

        now = timezone.now()
        live = [otp for otp in pending if otp.expires_at >= now]

        if not live:
            raise serializers.ValidationError(
                {"otp": "OTP expired. Request a new one."}
            )

        # Matched by hash rather than by "whichever is newest": an account can
        # hold a registration code and a login code at the same time, and
        # taking the newer one would reject the other as invalid when it is
        # perfectly good. The code itself says which row it belongs to.
        for otp_obj in live:
            if OTPService.verify_otp(attrs["otp"], otp_obj.code_hash):
                attrs["user"] = user
                attrs["otp_obj"] = otp_obj

                return attrs

        # Counted against the newest, which is the one the user is most likely
        # looking at — a wrong guess has to cost something or the six digits
        # are guessable at leisure.
        newest = live[0]
        newest.attempts += 1
        newest.save(update_fields=["attempts"])

        raise serializers.ValidationError(
            {"otp": "Invalid OTP."}
        )

    @staticmethod
    def _nothing_pending(user):
        """Say which of the two "no code" stories this is.

        A bare "OTP not found." covered both a code that was already spent and
        one that was never issued. They need different things from the user,
        and the old message sent people looking at the code in their hand
        rather than at the flow they were in.
        """
        if not user.is_verified:
            return (
                "No verification code is pending. Request a new one to "
                "finish signing up."
            )

        return (
            "No verification code is pending for this account. It may have "
            "been used already — request a new one."
        )
