"""Verifying a Google ID token.

The app signs the person in with Google on the device (Google Identity
Services on the web, the Google Sign-In SDKs on iOS and Android) and sends us
the ID token it got back. That token is a JWT signed by Google; checking the
signature against Google's published keys, the audience against our own
client IDs and the issuer is what makes its email a fact rather than a claim.
No secret is involved, and no redirect URI.
"""

import jwt
from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

INVALID = "This Google sign-in is not valid. Try again."


class GoogleSignInUnavailable(APIException):
    """503: not configured here, or Google's keys could not be fetched."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Google sign-in is not available right now. Try again."
    default_code = "google_unavailable"


class GoogleIdentityService:

    # One key client per process: it caches Google's keys, which rotate
    # rarely, so a sign-in does not fetch them every time.
    _jwks = None

    def verify(self, id_token):
        """The token's claims, once Google's signature, our audience, the
        issuer, the expiry and a verified email have all checked out."""
        client_ids = [c for c in settings.GOOGLE_OAUTH_CLIENT_IDS if c]

        if not client_ids:
            raise GoogleSignInUnavailable("Google sign-in is not available.")

        try:
            claims = jwt.decode(
                id_token,
                self._signing_key(id_token),
                algorithms=["RS256"],
                audience=client_ids,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
                leeway=30,
            )
        except jwt.PyJWKClientConnectionError as error:
            raise GoogleSignInUnavailable() from error
        except jwt.PyJWTError as error:
            raise ValidationError({"id_token": INVALID}) from error

        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise ValidationError({"id_token": INVALID})

        # Google sends a boolean; older tokens sent the string.
        if not claims.get("email") or claims.get("email_verified") not in (
            True,
            "true",
        ):
            raise ValidationError(
                {"id_token": "Google has not verified this email address."}
            )

        return claims

    def _signing_key(self, id_token):
        if GoogleIdentityService._jwks is None:
            GoogleIdentityService._jwks = jwt.PyJWKClient(
                GOOGLE_CERTS_URL, cache_keys=True, lifespan=3600
            )

        return GoogleIdentityService._jwks.get_signing_key_from_jwt(
            id_token
        ).key
