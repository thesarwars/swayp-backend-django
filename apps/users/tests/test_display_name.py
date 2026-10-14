"""Web B4: one display name on every endpoint, never the email."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.teams.services.team_service import TeamService
from apps.users.models import AccountType, Profile
from apps.vendors.factories import UserFactory


class DisplayNameTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def names(self, user):
        self.client.force_authenticate(user=user)
        TeamService().ensure_owner_seat(user)

        return {
            "profile": self.client.get("/api/v1/users/profile").json()["data"]["full_name"],
            "summary": self.client.get("/api/v1/dashboard/profile-summary").json()["data"]["full_name"],
            "greeting": self.client.get("/api/v1/dashboard/home").json()["data"]["greeting"]["name"],
            "team": self.client.get("/api/v1/teams/members").json()["data"][0]["name"],
        }

    def test_every_endpoint_agrees(self):
        user = UserFactory(first_name="Jane", last_name="Smith")
        Profile.objects.create(user=user, full_name="Jane Smith",
                               account_type=AccountType.INDIVIDUAL)

        self.assertEqual(self.names(user), {
            "profile": "Jane Smith", "summary": "Jane Smith",
            "greeting": "Jane", "team": "Jane Smith",
        })

    def test_an_email_is_never_shown_as_a_name(self):
        user = UserFactory(first_name="", last_name="")
        Profile.objects.create(user=user, full_name=user.email,
                               account_type=AccountType.INDIVIDUAL)

        names = self.names(user)

        self.assertEqual(names["profile"], "")
        self.assertEqual(names["summary"], "")
        self.assertEqual(names["greeting"], "")
        self.assertIsNone(names["team"])

    def test_a_lazily_created_profile_does_not_store_the_email(self):
        user = UserFactory(first_name="", last_name="")
        self.client.force_authenticate(user=user)

        self.client.get("/api/v1/users/profile")

        self.assertEqual(Profile.objects.get(user=user).full_name, "")
