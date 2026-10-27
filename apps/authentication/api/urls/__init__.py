from .google_login import urlpatterns as google_login_urls
from .mfa import urlpatterns as mfa_urls
from .otp import urlpatterns as otp_urls
from .password_reset import urlpatterns as password_reset_urls
from .phone_login import urlpatterns as phone_login_urls
from .sessions import urlpatterns as sessions_urls
from .token import urlpatterns as token_urls
from .user_login import urlpatterns as user_login_urls
from .user_registration import urlpatterns as user_registration_urls

urlpatterns = [
    *user_registration_urls,
    *user_login_urls,
    *phone_login_urls,
    *google_login_urls,
    *otp_urls,
    *token_urls,
    *sessions_urls,
    *mfa_urls,
    *password_reset_urls,
]
