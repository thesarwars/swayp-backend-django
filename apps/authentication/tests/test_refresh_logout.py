"""Refresh and logout. Both answered 500 on every call: the services read
``refresh.user``, which simplejwt tokens do not have."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.models import RefreshToken
from apps.vendors.factories import UserFactory


class RefreshLogoutTests(TestCase):

    def setUp(self):
        self.user = UserFactory(is_active=True, is_verified=True)
        self.user.set_password("Str0ng!Passphrase1")
        self.user.save()
        self.client = APIClient()
        self.tokens = self.client.post(
            "/api/v1/auth/login",
            {"email": self.user.email, "password": "Str0ng!Passphrase1"},
            format="json",
        ).json()["data"]

    def refresh(self, token):
        return self.client.post(
            "/api/v1/auth/refresh", {"refresh": token}, format="json"
        )

    def test_refresh_returns_a_working_pair_and_records_the_session(self):
        response = self.refresh(self.tokens["refresh"])

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertNotEqual(data["refresh"], self.tokens["refresh"])
        self.assertEqual(RefreshToken.objects.filter(user=self.user).count(), 2)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {data['access']}")
        self.assertEqual(
            self.client.get("/api/v1/users/profile").status_code, 200
        )

    def test_a_rotated_refresh_token_cannot_be_used_again(self):
        self.refresh(self.tokens["refresh"])

        response = self.refresh(self.tokens["refresh"])

        self.assertEqual(response.status_code, 401)

    def test_logout_revokes_and_blacklists(self):
        response = self.client.post(
            "/api/v1/auth/logout", {"refresh": self.tokens["refresh"]},
            format="json",
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            RefreshToken.objects.filter(
                user=self.user, revoked_at__isnull=True
            ).exists()
        )
        self.assertEqual(self.refresh(self.tokens["refresh"]).status_code, 401)

    def test_logout_with_a_bad_token_is_a_400(self):
        response = self.client.post(
            "/api/v1/auth/logout", {"refresh": "garbage"}, format="json"
        )

        self.assertEqual(response.status_code, 400)
