"""Client metadata extraction for audit and consent records.

`REMOTE_ADDR` is the proxy's address once the app sits behind a load balancer,
so anything legally significant — a NACHA standing authorization, an audit
entry — has to consult `X-Forwarded-For` first.
"""

#: Header order to try. The first entry of X-Forwarded-For is the client; the
#: rest are proxies that appended themselves.
_FORWARDED_HEADERS = (
    "HTTP_X_FORWARDED_FOR",
    "HTTP_X_REAL_IP",
)

USER_AGENT_MAX_LENGTH = 1024


def client_ip(request):
    """The originating client IP, or ``None`` if it cannot be determined.

    Callers persisting a consent artifact should treat ``None`` as a hard
    failure rather than substituting a placeholder — a consent record with a
    fabricated IP is worse than no record.
    """
    if request is None:
        return None

    meta = getattr(request, "META", {}) or {}

    for header in _FORWARDED_HEADERS:
        value = meta.get(header)

        if not value:
            continue

        # "client, proxy1, proxy2" — the client is the first hop.
        candidate = value.split(",")[0].strip()

        if candidate:
            return candidate

    return (meta.get("REMOTE_ADDR") or "").strip() or None


def user_agent(request):
    """The client's User-Agent, truncated to a storable length."""
    if request is None:
        return ""

    meta = getattr(request, "META", {}) or {}

    return (meta.get("HTTP_USER_AGENT") or "")[:USER_AGENT_MAX_LENGTH]


def request_meta(request):
    """``{"ip": ..., "user_agent": ...}`` for the service layer.

    Views call this so services never need to touch a request object.
    """
    return {
        "ip": client_ip(request),
        "user_agent": user_agent(request),
    }
