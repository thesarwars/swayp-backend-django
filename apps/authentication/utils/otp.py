import secrets
from django.contrib.auth.hashers import check_password


OTP_LENGTH = 6

#: Shared by every path that checks a code, so the client sees one message.
TOO_MANY_ATTEMPTS = "Too many incorrect attempts. Request a new code."


class OTPService:
    

    @staticmethod
    def generate_otp() -> str:
       

        digits = "0123456789"

        return "".join(
            secrets.choice(digits)
            for _ in range(OTP_LENGTH)
        )

    @staticmethod
    def verify_otp(otp: str, stored: str) -> bool:
        """Compare in constant time. A stored value containing "$" is a hash
        written before codes were kept in plain text; those are checked as
        hashes until they expire, so a code in flight across the deploy
        still works."""
        if "$" in (stored or ""):
            return check_password(otp, stored)

        return secrets.compare_digest(str(otp), str(stored))
