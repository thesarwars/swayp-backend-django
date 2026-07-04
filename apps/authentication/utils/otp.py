import secrets
from django.contrib.auth.hashers import check_password, make_password


OTP_LENGTH = 6


class OTPService:
    

    @staticmethod
    def generate_otp() -> str:
       

        digits = "0123456789"

        return "".join(
            secrets.choice(digits)
            for _ in range(OTP_LENGTH)
        )

    @staticmethod
    def hash_otp(otp: str) -> str:
       

        return make_password(otp)

    @staticmethod
    def verify_otp(
        otp: str,
        hashed_otp: str,
    ) -> bool:
        

        return check_password(
            otp,
            hashed_otp,
        )