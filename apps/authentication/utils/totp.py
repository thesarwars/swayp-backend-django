"""Time-based one-time passwords (RFC 6238), as authenticator apps make them.

Standard library only: HMAC-SHA1 over a 30-second counter, six digits, which
is the combination Google Authenticator, 1Password, Authy and Microsoft
Authenticator all default to. Anything else is a setting some of them ignore.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
STEP_SECONDS = 30

#: Codes either side of now that still count. One step covers a phone clock
#: up to 30 seconds off and a code typed just as it rolled over.
DRIFT_STEPS = 1

ISSUER = "Swayp"


def new_secret():
    """160 random bits, base32 without padding: what the apps expect."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret):
    padded = secret + "=" * (-len(secret) % 8)

    return base64.b32decode(padded.upper())


def code_at(secret, step):
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1)
    digest = digest.digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF

    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(now=None):
    return int((time.time() if now is None else now) // STEP_SECONDS)


def matching_step(secret, code, now=None):
    """The time step ``code`` belongs to, or None if it matches none in the
    drift window. The caller stores the step so a code works once."""
    code = (code or "").strip().replace(" ", "")

    if len(code) != DIGITS or not code.isdigit():
        return None

    step = current_step(now)

    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if hmac.compare_digest(code_at(secret, candidate), code):
            return candidate

    return None


def provisioning_uri(secret, account_name):
    """The otpauth:// URI an authenticator app reads from a QR code."""
    label = quote(f"{ISSUER}:{account_name}")
    query = urlencode(
        {
            "secret": secret,
            "issuer": ISSUER,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP_SECONDS,
        }
    )

    return f"otpauth://totp/{label}?{query}"
