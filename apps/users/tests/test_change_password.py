"""Web §4: change password while signed in."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.authentication.models import RefreshToken
from apps.vendors.factories import UserFactory

OLD = "Str0ng!Passphrase1"
NEW = "An0ther!Passphrase2"


class ChangePasswordTests(TestCase):

    def setUp(self):
        self.user = UserFactory(is_active=True, is_verified=True)
        self.user.set_password(OLD)
        self.user.save()
        self.client = APIClient()
        self.old = self.client.post("/api/v1/auth/login", {
            "email": self.user.email, "password": OLD}, format="json"
        ).json()["data"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.old['access']}")

    def change(self, current=OLD, new=NEW):
        return self.client.post("/api/v1/users/password", {
            "current_password": current, "new_password": new}, format="json")

    def test_it_changes_and_signs_out_other_sessions(self):
        response = self.change()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["refresh"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW))

        reused = APIClient().post("/api/v1/auth/refresh",
                                  {"refresh": self.old["refresh"]},
                                  format="json")
        self.assertEqual(reused.status_code, 401)
        self.assertEqual(
            RefreshToken.objects.filter(user=self.user,
                                        revoked_at__isnull=True).count(), 1)

    def test_a_wrong_current_password(self):
        response = self.change(current="nope")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_credentials")

    def test_the_rules_and_reuse_apply(self):
        weak = self.change(new="alllowercase1!")
        same = self.change(new=OLD)

        self.assertIn("new_password", weak.json()["errors"])
        self.assertEqual(same.status_code, 400)

    def test_signed_out_is_401(self):
        self.client.credentials()

        self.assertEqual(self.change().status_code, 401)
