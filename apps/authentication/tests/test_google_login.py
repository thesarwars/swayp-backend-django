"""Sign in with Google: POST /auth/login/google.

Tokens are signed here with a throwaway RSA key standing in for Google's, so
the real decode runs — signature, audience, issuer, expiry — and only the
fetch of Google's public key is replaced.
"""

import time
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.authentication.models import RefreshToken
from apps.authentication.services.google_identity_service import (
    GoogleIdentityService,
)
from apps.users.models import AccountType, Profile
from apps.vendors.factories import UserFactory

User = get_user_model()

URL = "/api/v1/auth/login/google"
WEB = "web-client.apps.googleusercontent.com"
IOS = "ios-client.apps.googleusercontent.com"

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_token(key=KEY, **overrides):
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": WEB,
        "sub": "1098765",
        "email": "ada@example.com",
        "email_verified": True,
        "name": "Ada Lovelace",
        "given_name": "Ada",
        "family_name": "Lovelace",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}

    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


@override_settings(GOOGLE_OAUTH_CLIENT_IDS=[WEB, IOS])
class GoogleLoginTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        patcher = mock.patch.object(
            GoogleIdentityService, "_signing_key",
            return_value=KEY.public_key(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, token=None, **body):
        return self.client.post(
            URL, {"id_token": token or google_token(), **body}, format="json"
        )

    # --- new accounts -----------------------------------------------------

    def test_a_new_person_gets_an_account_and_tokens(self):
        response = self._post(account_type=AccountType.INDIVIDUAL,
                              terms_accepted=True)

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["is_new_user"])
        self.assertTrue(data["access"] and data["refresh"])

        user = User.objects.get(email="ada@example.com")
        self.assertEqual(user.google_sub, "1098765")
        self.assertTrue(user.is_active and user.is_verified)
        self.assertFalse(user.has_usable_password())
        self.assertEqual((user.first_name, user.last_name), ("Ada", "Lovelace"))

        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.account_type, AccountType.INDIVIDUAL)
        self.assertEqual(profile.full_name, "Ada Lovelace")
        self.assertIsNotNone(profile.terms_accepted_at)
        self.assertIsNone(profile.signatory_confirmed_at)
        self.assertEqual(RefreshToken.objects.filter(user=user).count(), 1)

    def test_signatory_confirmed_is_recorded(self):
        self._post(signatory_confirmed=True)

        profile = Profile.objects.get(user__email="ada@example.com")
        self.assertIsNotNone(profile.signatory_confirmed_at)

    def test_a_business_signup_lands_on_the_business_step(self):
        self._post()

        user = User.objects.get(email="ada@example.com")
        onboarding = self.client.get(
            "/api/v1/users/onboarding",
            HTTP_AUTHORIZATION=f"Bearer {self._post().json()['data']['access']}",
        ).json()["data"]

        self.assertEqual(user.profile.account_type, AccountType.BUSINESS)
        self.assertEqual(onboarding["current_step"], 1)

    def test_the_second_sign_in_is_not_new(self):
        self._post()

        response = self._post()

        self.assertFalse(response.json()["data"]["is_new_user"])
        self.assertEqual(User.objects.filter(email="ada@example.com").count(), 1)

    def test_an_ios_token_is_accepted_too(self):
        self.assertEqual(self._post(google_token(aud=IOS)).status_code, 200)

    # --- existing accounts ------------------------------------------------

    def test_an_existing_password_account_is_linked_not_duplicated(self):
        existing = UserFactory(email="ada@example.com", is_active=True,
                               is_verified=True)

        data = self._post(google_token(email="Ada@Example.com")).json()["data"]

        existing.refresh_from_db()
        self.assertFalse(data["is_new_user"])
        self.assertEqual(existing.google_sub, "1098765")
        self.assertEqual(User.objects.count(), 1)

    def test_the_sub_wins_when_the_google_email_changed(self):
        linked = UserFactory(email="old@example.com", google_sub="1098765",
                             is_active=True, is_verified=True)

        self._post(google_token(email="new@example.com"))

        self.assertEqual(User.objects.count(), 1)
        linked.refresh_from_db()
        self.assertEqual(linked.email, "old@example.com")

    def test_an_unfinished_signup_is_completed(self):
        pending = UserFactory(email="ada@example.com", is_active=False,
                              is_verified=False)

        self.assertEqual(self._post().status_code, 200)

        pending.refresh_from_db()
        self.assertTrue(pending.is_active and pending.is_verified)

    def test_a_deactivated_account_is_refused(self):
        UserFactory(email="ada@example.com", is_active=False, is_verified=True)

        response = self._post()

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("data", response.json())

    def test_an_email_tied_to_another_google_account_is_refused(self):
        UserFactory(email="ada@example.com", google_sub="someone-else",
                    is_active=True, is_verified=True)

        response = self._post()

        self.assertEqual(response.status_code, 400)
        self.assertIn("id_token", response.json()["errors"])

    # --- tokens that must not work ----------------------------------------

    def _refused(self, token):
        response = self._post(token)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_another_apps_audience_is_refused(self):
        self._refused(google_token(aud="someone-elses.apps.googleusercontent.com"))

    def test_a_forged_signature_is_refused(self):
        self._refused(google_token(key=OTHER_KEY))

    def test_an_expired_token_is_refused(self):
        self._refused(google_token(iat=int(time.time()) - 7200,
                                   exp=int(time.time()) - 3600))

    def test_a_foreign_issuer_is_refused(self):
        self._refused(google_token(iss="https://evil.example.com"))

    def test_an_unverified_email_is_refused(self):
        self._refused(google_token(email_verified=False))

    def test_garbage_is_refused(self):
        self._refused("not-a-jwt")

    @override_settings(GOOGLE_OAUTH_CLIENT_IDS=[])
    def test_unconfigured_is_a_503(self):
        self.assertEqual(self._post().status_code, 503)

    def test_unreachable_google_is_a_503(self):
        with mock.patch.object(
            GoogleIdentityService, "_signing_key",
            side_effect=jwt.PyJWKClientConnectionError("down"),
        ):
            self.assertEqual(self._post().status_code, 503)
