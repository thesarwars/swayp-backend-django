"""The token that stands in for a verified reset code (AUTH-4).

The reset screens go email → code → new password. Checking the code at the
code step means spending it there, so the new-password step needs something
else to prove the code was right: this token.

It is signed, not stored, so it needs no table. It carries the account and a
fingerprint of the current password hash, which makes it single-use without
any bookkeeping: once the password changes, the fingerprint no longer matches
and every token issued before the change is dead. A rejected password (reuse,
weak) leaves the hash alone, so the same token can be retried.

The fingerprint is an HMAC of the hash, never the hash itself: the payload of a
signed token is readable by whoever holds it.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.utils.crypto import constant_time_compare, salted_hmac
from rest_framework.exceptions import ValidationError

User = get_user_model()

SALT = "apps.authentication.reset_token"
INVALID = "This reset token is invalid or has expired. Request a new code."


def _max_age():
    return getattr(settings, "PASSWORD_RESET_TOKEN_MAX_AGE_SECONDS", 600)


def _fingerprint(user):
    return salted_hmac(SALT, user.password).hexdigest()[:20]


class ResetTokenService:

    @staticmethod
    def issue(user):
        token = signing.dumps(
            {"u": str(user.pk), "f": _fingerprint(user)},
            salt=SALT,
        )

        return {"reset_token": token, "expires_in": _max_age()}

    @staticmethod
    def resolve(*, email, token):
        """The account the token was issued for, or a 400 on ``reset_token``.

        ``email`` must match: the token is only good for the account the
        client says it is resetting.
        """
        try:
            payload = signing.loads(token, salt=SALT, max_age=_max_age())
        except signing.BadSignature:
            # SignatureExpired is a subclass, so expiry lands here too.
            raise ValidationError({"reset_token": [INVALID]})

        user = User.objects.filter(pk=payload.get("u")).first()

        if (
            user is None
            or user.email.lower() != email.lower().strip()
            or not constant_time_compare(
                payload.get("f", ""), _fingerprint(user)
            )
        ):
            raise ValidationError({"reset_token": [INVALID]})

        return user
