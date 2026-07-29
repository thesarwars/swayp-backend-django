"""OTP resend throttling (E2-S2).

Two limits, both per user+purpose: a minimum gap between sends, and an hourly
cap. Counting OTP rows rather than a cache key means the limit survives a
restart and cannot be dodged by hitting a different worker.
"""

from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from apps.authentication.models import OTP
from apps.common.exceptions import OTPThrottledException


def _setting(name, default):
    return getattr(settings, name, default)


class OTPThrottleService:

    @property
    def min_gap_seconds(self):
        return _setting("OTP_RESEND_MIN_GAP_SECONDS", 60)

    @property
    def hourly_limit(self):
        return _setting("OTP_RESEND_HOURLY_LIMIT", 5)

    def check(self, *, user, purpose):
        """Raise if a resend is not allowed yet. Returns retry-after seconds."""
        now = timezone.now()

        recent = OTP.objects.filter(
            user=user,
            purpose=purpose,
            created_at__gte=now - timedelta(hours=1),
        ).order_by("-created_at")

        window = list(recent[: self.hourly_limit + 1])

        if window:
            elapsed = (now - window[0].created_at).total_seconds()

            if elapsed < self.min_gap_seconds:
                raise OTPThrottledException(
                    retry_after=int(self.min_gap_seconds - elapsed),
                )

        if len(window) >= self.hourly_limit:
            oldest = window[self.hourly_limit - 1]
            retry_after = int(
                (oldest.created_at + timedelta(hours=1) - now).total_seconds()
            )

            raise OTPThrottledException(retry_after=max(retry_after, 1))

        return 0
