"""Failed-login lockout (E2).

``User.failed_login_attempts`` and ``User.locked_until`` have existed since the
first migration with nothing reading or writing them. Fields without a caller
are not a feature — password guessing was unbounded, and the model looked like
it was protected.

Two rules shape the behaviour:

* **A locked account says so, and says for how long.** Hiding the lock behind
  "invalid email or password" would leave a legitimate user who mistyped twice
  guessing why their correct password stopped working.
* **The lock is on the account, not the password check.** It is enforced
  before the credentials are looked at, so an attacker cannot use response
  timing to tell a locked account from a wrong password.
"""

import datetime as dt

from django.conf import settings
from django.utils import timezone


def _max_attempts():
    return getattr(settings, "LOGIN_MAX_ATTEMPTS", 5)


def _lockout_minutes():
    return getattr(settings, "LOGIN_LOCKOUT_MINUTES", 15)


class LockoutService:

    def is_locked(self, user, *, now=None):
        if user is None or user.locked_until is None:
            return False

        return (now or timezone.now()) < user.locked_until

    def minutes_remaining(self, user, *, now=None):
        if not self.is_locked(user, now=now):
            return 0

        delta = user.locked_until - (now or timezone.now())

        # Round up: "try again in 0 minutes" is not an instruction.
        return max(1, int(delta.total_seconds() // 60) + 1)

    def record_failure(self, user, *, now=None):
        """Count one failed attempt and lock once the ceiling is reached."""
        if user is None:
            # An unknown email must not create anything or behave differently;
            # user enumeration is the thing this must not become.
            return None

        now = now or timezone.now()

        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        fields = ["failed_login_attempts"]

        if user.failed_login_attempts >= _max_attempts():
            user.locked_until = now + dt.timedelta(minutes=_lockout_minutes())
            fields.append("locked_until")

        user.save(update_fields=fields)

        return user

    def record_success(self, user):
        """Clear the counter. A correct password ends the sequence.

        Also clears an expired lock, so the row does not carry a stale
        ``locked_until`` that a later reader might misinterpret.
        """
        if user is None:
            return None

        if not user.failed_login_attempts and user.locked_until is None:
            return user

        user.failed_login_attempts = 0
        user.locked_until = None
        user.save(update_fields=["failed_login_attempts", "locked_until"])

        return user
