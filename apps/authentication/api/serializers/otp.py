from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from apps.authentication.models import OTP, OTPChannel, OTPPurpose
from apps.authentication.utils.otp import TOO_MANY_ATTEMPTS, OTPService

User = get_user_model()

#: What ``/auth/verify-otp`` can complete.
#:
#: LOGIN is not one of them, and leaving it in would have undone the change
#: that made a password sufficient to sign in. ``/auth/resend-otp`` will issue
#: a LOGIN code to any registered address, so a verify that accepted one would
#: still hand out tokens for possession of the inbox alone — the password
#: becomes optional again through a second door, and the inbox is the same
#: place a password reset lands.
#:
#: The phone flow still issues LOGIN codes and still spends them, at
#: ``/auth/login/phone/verify``, where the caller has to know the phone number
#: as well.
#:
#: RESET_PASSWORD is verifiable so a wrong code shows on the code screen,
#: before the user has typed a new password twice (AUTH-4). It does not sign
#: anyone in: it answers with a short-lived ``reset_token`` that
#: ``/auth/reset-password`` takes in place of the code. See
#: ``ResetTokenService``.
VERIFIABLE_PURPOSES = (
    OTPPurpose.REGISTRATION,
    OTPPurpose.RESET_PASSWORD,
)

#: What a request without ``purpose`` searches. Registration only: a reset
#: code has to be named, so a client finishing a sign-up can never be handed a
#: reset token instead of its session.
DEFAULT_PURPOSES = (OTPPurpose.REGISTRATION,)


#: The answer when no code is waiting, for an account or for an address with
#: no account. It used to say "for this account" or "to finish signing up",
#: which told a stranger the address was registered and whether it was
#: verified (SEC-3).
NO_CODE_PENDING = "No code is pending for this address. Request a new one."


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    purpose = serializers.ChoiceField(choices=OTPPurpose.choices)

    # Accepted so the SMS screens can be built, but validated to EMAIL by the
    # service — SMS is deferred this release (E2-S1).
    channel = serializers.ChoiceField(
        choices=OTPChannel.choices,
        required=False,
        default=OTPChannel.EMAIL,
    )

    def validate(self, attrs):
        email = attrs["email"].lower().strip()

        # None for an unknown address: the view answers the same either way
        # (SEC-3), so this must not say which it is.
        attrs["user"] = User.objects.filter(email__iexact=email).first()
        attrs["email"] = email

        return attrs


class VerifyOTPSerializer(serializers.Serializer):
    """Spend an emailed code: finish a registration, or check a reset code.

    ``purpose`` defaults to REGISTRATION. ``RESET_PASSWORD`` has to be named.
    A client sending ``LOGIN`` is answered with a validation error naming what
    is valid, rather than the older "OTP not found." — which read as "your
    code is wrong" when it meant "that flow has no code here".
    """

    email = serializers.EmailField()

    otp = serializers.CharField(
        min_length=6,
        max_length=6,
    )

    purpose = serializers.ChoiceField(
        choices=[(purpose.value, purpose.label) for purpose in VERIFIABLE_PURPOSES],
        required=False,
    )

    def validate(self, attrs):
        email = attrs["email"].lower().strip()

        user = User.objects.filter(email__iexact=email).first()

        purposes = (
            [attrs["purpose"]] if attrs.get("purpose") else list(DEFAULT_PURPOSES)
        )

        pending = [] if user is None else list(
            OTP.objects.filter(
                user=user,
                purpose__in=purposes,
                used_at__isnull=True,
            ).order_by("-created_at")
        )

        if not pending:
            if purposes == [OTPPurpose.RESET_PASSWORD]:
                raise serializers.ValidationError(
                    {"otp": "No reset code is pending. Request a new one."}
                )

            # An unknown address lands here too, with the same words as an
            # account that has no code (SEC-3).
            raise serializers.ValidationError({"otp": NO_CODE_PENDING})

        now = timezone.now()
        live = [otp for otp in pending if otp.expires_at >= now]

        if not live:
            raise serializers.ValidationError(
                {"otp": "OTP expired. Request a new one."}
            )

        live = [otp for otp in live if not otp.is_exhausted]

        if not live:
            raise serializers.ValidationError({"otp": TOO_MANY_ATTEMPTS})

        # Matched by hash rather than by "whichever is newest". With one
        # verifiable purpose the two rarely differ, but a resend issued while
        # the user was reading the first email leaves two live rows, and the
        # code in front of them is as likely to be the older one.
        for otp_obj in live:
            if OTPService.verify_otp(attrs["otp"], otp_obj.code):
                attrs["user"] = user
                attrs["otp_obj"] = otp_obj

                return attrs

        # Counted against the newest, which is the one the user is most likely
        # looking at — a wrong guess has to cost something or the six digits
        # are guessable at leisure.
        newest = live[0]
        newest.attempts += 1
        newest.save(update_fields=["attempts"])

        raise serializers.ValidationError({"otp": "Invalid OTP."})


class VerifyOTPResponseSerializer(serializers.Serializer):
    """A session for REGISTRATION, a reset token for RESET_PASSWORD."""

    purpose = serializers.ChoiceField(choices=OTPPurpose.choices)
    access = serializers.CharField(required=False)
    refresh = serializers.CharField(required=False)
    reset_token = serializers.CharField(
        required=False, help_text="RESET_PASSWORD only; send to reset-password."
    )
    expires_in = serializers.IntegerField(
        required=False, help_text="Seconds the reset_token stays valid."
    )
