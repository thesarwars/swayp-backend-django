"""Password reuse prevention (E2-S4).

Every password set is recorded so a reset cannot land on one the user has used
before. Only hashes are kept, and the list is pruned so it does not grow
without bound.
"""

from django.conf import settings
from django.contrib.auth.hashers import check_password
from rest_framework.exceptions import ValidationError

from apps.authentication.models import PasswordHistory

#: How many previous passwords a new one is checked against.
DEFAULT_COMPARE_DEPTH = 1

#: How many rows to retain per user.
DEFAULT_KEEP = 5


class PasswordHistoryService:

    @property
    def compare_depth(self):
        return getattr(
            settings, "PASSWORD_HISTORY_COMPARE_DEPTH", DEFAULT_COMPARE_DEPTH
        )

    @property
    def keep(self):
        return getattr(settings, "PASSWORD_HISTORY_KEEP", DEFAULT_KEEP)

    def recent_hashes(self, user, limit=None):
        limit = limit or self.compare_depth

        return list(
            PasswordHistory.objects.filter(user=user).values_list(
                "password_hash", flat=True
            )[:limit]
        )

    def assert_not_reused(self, *, user, raw_password):
        """Raise if ``raw_password`` matches a recent one, or the current one."""
        candidates = self.recent_hashes(user)

        # The live password may predate history (e.g. accounts created before
        # this shipped), so check it too.
        if user.password and user.password not in candidates:
            candidates.append(user.password)

        for password_hash in candidates:
            if password_hash and check_password(raw_password, password_hash):
                raise ValidationError(
                    {
                        "password": (
                            "New password must be different from your "
                            "previous password."
                        )
                    }
                )

    def record(self, *, user):
        """Store the user's current hash and prune old rows."""
        if not user.password:
            return None

        entry = PasswordHistory.objects.create(
            user=user,
            password_hash=user.password,
        )

        keep_ids = list(
            PasswordHistory.objects.filter(user=user).values_list(
                "id", flat=True
            )[: self.keep]
        )

        PasswordHistory.objects.filter(user=user).exclude(
            id__in=keep_ids
        ).delete()

        return entry
