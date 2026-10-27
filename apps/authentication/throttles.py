"""Per-IP limits on public auth endpoints."""

from rest_framework.throttling import SimpleRateThrottle


class RegisterRateThrottle(SimpleRateThrottle):
    """Registration attempts per client IP (SEC-3).

    Register has to say an address is taken, so the limit is what keeps it
    from being a fast way to test a list of addresses. Keyed on the IP
    nginx sets in X-Real-IP, not on X-Forwarded-For: the first entry of
    that is whatever the client chose to send, and a limit the caller can
    reset by changing a header is not a limit.
    """

    scope = "register"

    def get_cache_key(self, request, view):
        meta = request.META
        ip = (
            meta.get("HTTP_X_REAL_IP") or meta.get("REMOTE_ADDR") or ""
        ).strip()

        return self.cache_format % {"scope": self.scope, "ident": ip}


class MFARateThrottle(SimpleRateThrottle):
    """Two-step code attempts per client IP.

    Six digits are a million guesses; the per-challenge cap of five stops one
    sign-in being brute-forced, and this stops starting fresh ones to get
    around it. Same X-Real-IP keying as registration, for the same reason.
    """

    scope = "mfa"

    def get_cache_key(self, request, view):
        meta = request.META
        ip = (
            meta.get("HTTP_X_REAL_IP") or meta.get("REMOTE_ADDR") or ""
        ).strip()

        return self.cache_format % {"scope": self.scope, "ident": ip}
