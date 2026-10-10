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


class AddressThrottle:
    """The same limits, counted per address rather than per account (SEC-3).

    OTPThrottleService counts an account's OTP rows, so only a real account
    could ever be throttled: a 429 for one address and a 200 for another
    said which one was registered. This counts requests for the address
    itself, the same way whether or not an account uses it, so the throttle
    answers identically for both.
    """

    def __init__(self):
        self.limits = OTPThrottleService()

    def check(self, *, email, purpose):
        import hashlib

        from django.core.cache import cache

        digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
        key = f"otp-address:{purpose}:{digest}"
        now = timezone.now().timestamp()
        recent = [t for t in cache.get(key, []) if now - t < 3600]

        if recent and now - recent[-1] < self.limits.min_gap_seconds:
            raise OTPThrottledException(
                retry_after=int(self.limits.min_gap_seconds - (now - recent[-1]))
                or 1,
            )

        if len(recent) >= self.limits.hourly_limit:
            raise OTPThrottledException(
                retry_after=max(int(recent[0] + 3600 - now), 1)
            )

        cache.set(key, [*recent, now], timeout=3600)
