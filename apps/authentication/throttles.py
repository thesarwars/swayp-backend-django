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
