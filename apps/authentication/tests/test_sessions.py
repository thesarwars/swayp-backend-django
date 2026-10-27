"""Where you're signed in, and signing out of it.

Signing a session out has to stop it now, not when its access token would
have expired, so these tests use the access token after the sign-out rather
than only checking the row.
"""

import datetime as dt

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken as JWTRefresh

from apps.authentication.models import RefreshToken as Session
from apps.authentication.services.session_service import SID_CLAIM
from apps.vendors.factories import UserFactory

PASSWORD = "Str0ng!Passphrase1"


class Device:
    """One signed-in client: its own tokens and its own APIClient."""

    def __init__(self, user, agent):
        self.client = APIClient(HTTP_USER_AGENT=agent)
        self.tokens = self.client.post(
            "/api/v1/auth/login",
            {"email": user.email, "password": PASSWORD},
            format="json",
        ).json()["data"]
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self.tokens['access']}"
        )
        self.sid = JWTRefresh(self.tokens["refresh"])[SID_CLAIM]

    def get(self, path="/api/v1/users/profile"):
        return self.client.get(path)

    def refresh(self):
        return APIClient().post(
            "/api/v1/auth/refresh",
            {"refresh": self.tokens["refresh"]},
            format="json",
        )


class SessionTests(TestCase):

    def setUp(self):
        self.user = UserFactory(is_active=True, is_verified=True)
        self.user.set_password(PASSWORD)
        self.user.save()
        self.laptop = Device(self.user, "Mozilla/5.0 (Macintosh) Chrome/130")
        self.phone = Device(self.user, "Swayp/1.0 (iPhone; iOS 18)")

    def test_each_device_is_one_session_and_this_one_is_marked(self):
        response = self.laptop.get("/api/v1/auth/sessions")

        self.assertEqual(response.status_code, 200)
        sessions = response.data["data"]
        self.assertEqual(len(sessions), 2)

        current = [s for s in sessions if s["current"]]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["id"], self.laptop.sid)
        self.assertIn("Chrome", current[0]["user_agent"])

    def test_a_refresh_keeps_the_same_session(self):
        data = self.phone.refresh().json()["data"]

        self.assertEqual(JWTRefresh(data["refresh"])[SID_CLAIM], self.phone.sid)
        self.assertEqual(Session.objects.filter(user=self.user).count(), 2)

    def test_signing_out_another_device_stops_its_access_token_at_once(self):
        response = self.laptop.client.delete(
            f"/api/v1/auth/sessions/{self.phone.sid}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.phone.get().status_code, 401)
        self.assertEqual(self.phone.refresh().status_code, 401)
        self.assertEqual(self.laptop.get().status_code, 200)

    def test_sign_out_everywhere_keeps_this_device(self):
        response = self.laptop.client.post(
            "/api/v1/auth/sessions/revoke-all", {}, format="json"
        )

        self.assertEqual(response.data["data"]["revoked"], 1)
        self.assertEqual(self.phone.get().status_code, 401)
        self.assertEqual(self.laptop.get().status_code, 200)

    def test_sign_out_everywhere_can_include_this_device(self):
        self.laptop.client.post(
            "/api/v1/auth/sessions/revoke-all",
            {"include_current": True},
            format="json",
        )

        self.assertEqual(self.laptop.get().status_code, 401)
        self.assertEqual(self.phone.get().status_code, 401)

    def test_another_users_session_is_not_found(self):
        stranger = UserFactory(is_active=True, is_verified=True)
        stranger.set_password(PASSWORD)
        stranger.save()
        theirs = Device(stranger, "curl/8")

        response = self.laptop.client.delete(
            f"/api/v1/auth/sessions/{theirs.sid}"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(theirs.get().status_code, 200)

    def test_logout_ends_only_its_own_session(self):
        APIClient().post(
            "/api/v1/auth/logout",
            {"refresh": self.phone.tokens["refresh"]},
            format="json",
        )

        self.assertEqual(self.phone.get().status_code, 401)
        self.assertEqual(self.laptop.get().status_code, 200)

    def test_changing_the_password_signs_other_devices_out_at_once(self):
        response = self.laptop.client.post(
            "/api/v1/users/password",
            {
                "current_password": PASSWORD,
                "new_password": "An0ther!Passphrase2",
                "confirm_password": "An0ther!Passphrase2",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.phone.get().status_code, 401)

    def test_an_ended_session_is_not_listed(self):
        self.laptop.client.delete(f"/api/v1/auth/sessions/{self.phone.sid}")

        sessions = self.laptop.get("/api/v1/auth/sessions").data["data"]

        self.assertEqual([s["id"] for s in sessions], [self.laptop.sid])

    def test_use_moves_last_used_forward(self):
        stale = timezone.now() - dt.timedelta(hours=1)
        Session.objects.filter(id=self.phone.sid).update(last_used_at=stale)

        self.phone.get()

        self.assertGreater(
            Session.objects.get(id=self.phone.sid).last_used_at, stale
        )


class LegacyTokenTests(TestCase):
    """Tokens minted before sessions carried an id keep working, and are
    adopted into a session at their next refresh."""

    def test_a_token_without_a_session_is_adopted_on_refresh(self):
        user = UserFactory(is_active=True, is_verified=True)
        legacy = JWTRefresh.for_user(user)

        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {legacy.access_token}")
        self.assertEqual(client.get("/api/v1/users/profile").status_code, 200)

        response = client.post(
            "/api/v1/auth/refresh", {"refresh": str(legacy)}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        sid = JWTRefresh(response.json()["data"]["refresh"])[SID_CLAIM]
        self.assertTrue(Session.objects.filter(id=sid, user=user).exists())
