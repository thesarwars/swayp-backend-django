"""Two-step verification with an authenticator app (TOTP).

Optional for every user. Once on, every sign-in path (email and password,
Google, phone code) stops short of tokens and answers with a challenge; the
tokens come from completing it with a code from the app or a recovery code.

A challenge is a signed, five-minute token naming the user, good for five
attempts and one success. It is not a session and opens nothing else, so a
stolen password still has nowhere to go without the second factor.
"""

import hashlib
import secrets

from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.authentication.models import MFADevice, MFARecoveryCode
from apps.authentication.services.security_notice_service import notify
from apps.authentication.services.session_service import SessionService
from apps.authentication.utils import totp
from apps.common.error_codes import (
    ACCOUNT_LOCKED,
    INVALID_CREDENTIALS,
    MFA_ALREADY_ENABLED,
    MFA_CHALLENGE_INVALID,
    MFA_CODE_INVALID,
    MFA_NOT_ENABLED,
)

RECOVERY_CODE_COUNT = 10

CHALLENGE_SALT = "swayp.auth.mfa-challenge"
CHALLENGE_TTL_SECONDS = 5 * 60
CHALLENGE_MAX_ATTEMPTS = 5

#: Wrong sign-in codes per user before two-step sign-in pauses. Separate from
#: the password lockout, which a correct password resets: someone holding the
#: password could otherwise start challenge after challenge.
USER_MAX_FAILURES = 10
USER_LOCK_SECONDS = 15 * 60

#: The ways a challenge can be answered, for the client to offer.
METHODS = ("totp", "recovery_code")

_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def _new_recovery_code():
    # 10 characters from a 31-letter alphabet with no 0/o or 1/l/i to
    # misread: about 50 bits, printed as "abcde-fghjk".
    raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))

    return f"{raw[:5]}-{raw[5:]}"


def _normalise_recovery_code(code):
    return (code or "").strip().lower().replace("-", "").replace(" ", "")


def _digest(code):
    return hashlib.sha256(_normalise_recovery_code(code).encode()).hexdigest()


def _invalid_code():
    return ValidationError(
        {"code": "That code is not valid. Check your authenticator app."},
        code=MFA_CODE_INVALID,
    )


class MFAService:

    # --- state ------------------------------------------------------------

    @staticmethod
    def device(user):
        return MFADevice.objects.filter(user=user).first()

    @staticmethod
    def is_enabled(user):
        return MFADevice.objects.filter(
            user=user, confirmed_at__isnull=False
        ).exists()

    @staticmethod
    def status(user):
        device = MFAService.device(user)
        enabled = device is not None and device.is_enabled

        return {
            "enabled": enabled,
            "enabled_at": device.confirmed_at if enabled else None,
            "recovery_codes_remaining": (
                MFARecoveryCode.objects.filter(
                    user=user, used_at__isnull=True
                ).count()
                if enabled
                else 0
            ),
        }

    # --- turning it on ----------------------------------------------------

    @staticmethod
    @transaction.atomic
    def setup(user):
        """Start setup: a new secret for the app to scan. Replaces an
        unfinished setup; refused while MFA is on."""
        device = MFADevice.objects.select_for_update().filter(user=user).first()

        if device is not None and device.is_enabled:
            raise ValidationError(
                {"detail": "Two-step verification is already on."},
                code=MFA_ALREADY_ENABLED,
            )

        secret = totp.new_secret()

        if device is None:
            MFADevice.objects.create(user=user, secret=secret)
        else:
            device.secret = secret
            device.last_used_step = None
            device.save(update_fields=["secret", "last_used_step", "updated_at"])

        return {
            "secret": secret,
            "otpauth_uri": totp.provisioning_uri(secret, user.email),
        }

    @staticmethod
    @transaction.atomic
    def confirm(user, code):
        """Finish setup with a code from the app; returns the recovery codes,
        which are shown this once."""
        device = MFADevice.objects.select_for_update().filter(user=user).first()

        if device is None:
            raise ValidationError(
                {"detail": "Start setup first."}, code=MFA_NOT_ENABLED
            )

        if device.is_enabled:
            raise ValidationError(
                {"detail": "Two-step verification is already on."},
                code=MFA_ALREADY_ENABLED,
            )

        step = totp.matching_step(device.secret, code)

        if step is None:
            raise _invalid_code()

        device.confirmed_at = timezone.now()
        device.last_used_step = step
        device.save(
            update_fields=["confirmed_at", "last_used_step", "updated_at"]
        )

        codes = MFAService._replace_recovery_codes(user)
        notify(user, "MFA_ENABLED")

        return codes

    # --- checking a code --------------------------------------------------

    @staticmethod
    @transaction.atomic
    def verify(user, code, *, allow_recovery=True):
        """Accept a code from the app or, if allowed, a recovery code.

        Returns which it was. An app code works once: the step it belongs to
        is recorded and that step and older ones are refused after.
        """
        device = (
            MFADevice.objects.select_for_update()
            .filter(user=user, confirmed_at__isnull=False)
            .first()
        )

        if device is None:
            raise ValidationError(
                {"detail": "Two-step verification is not on."},
                code=MFA_NOT_ENABLED,
            )

        step = totp.matching_step(device.secret, code)

        if step is not None:
            if device.last_used_step is not None and step <= device.last_used_step:
                raise _invalid_code()

            device.last_used_step = step
            device.save(update_fields=["last_used_step", "updated_at"])

            return "totp"

        if allow_recovery:
            used = MFARecoveryCode.objects.filter(
                user=user, used_at__isnull=True, code_hash=_digest(code)
            ).update(used_at=timezone.now())

            if used:
                notify(user, "MFA_RECOVERY_CODE_USED")

                return "recovery_code"

        raise _invalid_code()

    # --- turning it off, new codes ----------------------------------------

    @staticmethod
    @transaction.atomic
    def disable(user, *, code, password=None, keep_session=None):
        """Turn MFA off. Needs a current code, and the password too when
        the account has one (a Google-only account has none to give).
        Every other session ends: if this was not the owner, they should not
        stay signed in anywhere the owner is not."""
        if user.has_usable_password() and not user.check_password(
            password or ""
        ):
            raise ValidationError(
                {"password": "Your password is not correct."},
                code=INVALID_CREDENTIALS,
            )

        MFAService.verify(user, code)

        MFADevice.objects.filter(user=user).delete()
        MFARecoveryCode.objects.filter(user=user).delete()
        SessionService.end_all(user, keep=keep_session)
        notify(user, "MFA_DISABLED")

    @staticmethod
    @transaction.atomic
    def regenerate_recovery_codes(user, code):
        """A new set of codes, which voids the old ones. Needs an app code:
        a recovery code buying ten more would make them unlimited."""
        MFAService.verify(user, code, allow_recovery=False)

        return MFAService._replace_recovery_codes(user)

    @staticmethod
    def _replace_recovery_codes(user):
        MFARecoveryCode.objects.filter(user=user).delete()
        codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
        MFARecoveryCode.objects.bulk_create(
            MFARecoveryCode(user=user, code_hash=_digest(code))
            for code in codes
        )

        return codes


class MFAChallenge:
    """The step between a correct password and the tokens."""

    @staticmethod
    def issue(user):
        nonce = secrets.token_urlsafe(16)
        cache.set(_attempts_key(nonce), 0, timeout=CHALLENGE_TTL_SECONDS)

        return signing.dumps({"u": str(user.pk), "n": nonce}, salt=CHALLENGE_SALT)

    @staticmethod
    def complete(token, code, request):
        """Answer a challenge; returns the session's token pair."""
        from apps.users.models.user import User

        try:
            payload = signing.loads(
                token, salt=CHALLENGE_SALT, max_age=CHALLENGE_TTL_SECONDS
            )
        except signing.BadSignature:
            raise _challenge_invalid()

        key = _attempts_key(payload["n"])
        attempts = cache.get(key)

        if attempts is None or attempts >= CHALLENGE_MAX_ATTEMPTS:
            # Expired, used, or out of attempts: sign in again.
            raise _challenge_invalid()

        user = User.objects.filter(pk=payload["u"], is_active=True).first()

        if user is None:
            raise _challenge_invalid()

        failures_key = _failures_key(user)

        if (cache.get(failures_key) or 0) >= USER_MAX_FAILURES:
            raise ValidationError(
                {
                    "detail": (
                        "Too many wrong codes. Try again in 15 minutes, or "
                        "use a recovery code then."
                    )
                },
                code=ACCOUNT_LOCKED,
            )

        try:
            method = MFAService.verify(user, code)
        except ValidationError:
            _bump(key, CHALLENGE_TTL_SECONDS)
            _bump(failures_key, USER_LOCK_SECONDS)
            raise

        # Spent: one challenge, one sign-in.
        cache.set(key, CHALLENGE_MAX_ATTEMPTS, timeout=CHALLENGE_TTL_SECONDS)
        cache.delete(failures_key)

        from apps.authentication.services.login_service import LoginService

        return {**LoginService.login(user, request), "mfa_method": method}


def _attempts_key(nonce):
    return f"mfa-challenge:{nonce}"


def _failures_key(user):
    return f"mfa-failures:{user.pk}"


def _bump(key, timeout):
    if not cache.add(key, 1, timeout=timeout):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=timeout)


def _challenge_invalid():
    return ValidationError(
        {
            "mfa_token": (
                "This sign-in has expired or had too many tries. "
                "Sign in again."
            )
        },
        code=MFA_CHALLENGE_INVALID,
    )
