"""The account can read and change its own profile.

Registration collected a full name, address and — for a business — trading
name, point of contact and billing address, and until now nothing could change
any of it. A typo in a business name was permanent, and a company that moved
office had no way to say so, which matters because the billing address is what
appears on the invoice.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.teams.factories import ActiveMemberFactory
from apps.teams.models import TeamRole
from apps.users.models.business_profile import BusinessProfile
from apps.users.models.individual_profile import IndividualProfile
from apps.users.models.profile import AccountType, Profile
from apps.users.services.profile_service import ProfileService
from apps.vendors.factories import UserFactory

URL = "/api/v1/users/profile"


class ProfileReadTests(TestCase):

    def setUp(self):
        self.user = UserFactory(first_name="Ada", last_name="Reed")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_an_account_with_no_profile_row_still_gets_one(self):
        """Accounts predate these models. Failing to open the settings screen
        is worse than showing it empty."""
        self.assertFalse(Profile.objects.filter(user=self.user).exists())

        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Profile.objects.filter(user=self.user).exists())

    def test_business_fields_are_null_for_an_individual(self):
        """Present, not absent — a client renders one form either way."""
        data = self.client.get(URL).data["data"]

        self.assertEqual(data["account_type"], AccountType.INDIVIDUAL)
        self.assertIsNone(data["business_name"])
        self.assertIsNone(data["poc_name"])

    def test_login_identifiers_are_reported(self):
        data = self.client.get(URL).data["data"]

        self.assertEqual(data["email"], self.user.email)
        self.assertIn("phone_number", data)
        self.assertIn("is_verified", data)


class BusinessProfileTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.profile = Profile.objects.create(
            user=self.user,
            account_type=AccountType.BUSINESS,
            full_name="Ada Reed",
            address="1 Old Street",
        )
        BusinessProfile.objects.create(
            profile=self.profile,
            business_name="Reed Tradng LLC",   # deliberate typo
            poc_name="Ada Reed",
            billing_address="1 Old Street",
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_a_typo_in_the_business_name_can_be_fixed(self):
        """The whole reason this endpoint exists."""
        response = self.client.patch(
            URL, {"business_name": "Reed Trading LLC"}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["data"]["business_name"], "Reed Trading LLC"
        )

    def test_moving_office_updates_the_billing_address(self):
        """It is what appears on the invoice."""
        self.client.patch(
            URL, {"billing_address": "42 New Road"}, format="json"
        )

        self.assertEqual(
            BusinessProfile.objects.get(
                profile=self.profile
            ).billing_address,
            "42 New Road",
        )

    def test_a_partial_update_leaves_everything_else_alone(self):
        self.client.patch(URL, {"poc_name": "Sam Ortiz"}, format="json")

        branch = BusinessProfile.objects.get(profile=self.profile)

        self.assertEqual(branch.poc_name, "Sam Ortiz")
        self.assertEqual(branch.business_name, "Reed Tradng LLC")
        self.assertEqual(branch.billing_address, "1 Old Street")

    def test_account_type_cannot_be_changed_through_this_endpoint(self):
        """It changes what the account *is*, not a detail about it."""
        self.client.patch(
            URL, {"account_type": "INDIVIDUAL", "poc_name": "X"},
            format="json",
        )
        self.profile.refresh_from_db()

        self.assertEqual(self.profile.account_type, AccountType.BUSINESS)

    def test_email_cannot_be_changed_through_this_endpoint(self):
        """It is a login identifier verified by OTP, so changing it is an
        authentication flow rather than a profile edit."""
        original = self.user.email

        self.client.patch(
            URL, {"email": "attacker@example.com", "poc_name": "X"},
            format="json",
        )
        self.user.refresh_from_db()

        self.assertEqual(self.user.email, original)


class IndividualProfileTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.profile = Profile.objects.create(
            user=self.user,
            account_type=AccountType.INDIVIDUAL,
            full_name="Sam Ortiz",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_an_individual_can_set_a_billing_address(self):
        self.client.patch(
            URL, {"billing_address": "9 Elm Street"}, format="json"
        )

        self.assertEqual(
            IndividualProfile.objects.get(
                profile=self.profile
            ).billing_address,
            "9 Elm Street",
        )

    def test_business_fields_are_ignored_on_an_individual_account(self):
        """The serializer accepts them for one shared form; the service
        applies only what the account type actually has."""
        response = self.client.patch(
            URL,
            {"business_name": "Sneaky LLC", "full_name": "Sam O"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["data"]["business_name"])
        self.assertEqual(response.data["data"]["full_name"], "Sam O")


class ProfileWriteRulesTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_an_empty_update_is_refused(self):
        response = self.client.patch(URL, {}, format="json")

        self.assertEqual(response.status_code, 400)

    def test_the_user_row_is_kept_in_step_with_the_name(self):
        """The Stripe customer and the dashboard greeting read first_name;
        letting them disagree with the profile the customer just edited would
        show two different names in one product."""
        self.client.patch(URL, {"full_name": "Dana Reed"}, format="json")
        self.user.refresh_from_db()

        self.assertEqual(self.user.first_name, "Dana")
        self.assertEqual(self.user.last_name, "Reed")

    def test_a_single_word_name_does_not_crash(self):
        self.client.patch(URL, {"full_name": "Cher"}, format="json")
        self.user.refresh_from_db()

        self.assertEqual(self.user.first_name, "Cher")
        self.assertEqual(self.user.last_name, "")

    def test_it_requires_authentication(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)


class ProfileIsAccountScopedTests(TestCase):
    """A team member opening settings sees the business they work for."""

    def setUp(self):
        self.owner = UserFactory()
        Profile.objects.create(
            user=self.owner,
            account_type=AccountType.BUSINESS,
            full_name="Owner Name",
        )
        BusinessProfile.objects.create(
            profile=Profile.objects.get(user=self.owner),
            business_name="Reed Trading LLC",
            poc_name="Ada Reed",
            billing_address="1 Old Street",
        )
        self.member = ActiveMemberFactory(
            account=self.owner, role=TeamRole.MEMBER
        )

    def test_a_member_reads_the_accounts_profile(self):
        client = APIClient()
        client.force_authenticate(user=self.member.user)

        data = client.get(URL).data["data"]

        self.assertEqual(data["business_name"], "Reed Trading LLC")

    def test_a_stranger_sees_their_own_empty_profile(self):
        client = APIClient()
        client.force_authenticate(user=UserFactory())

        data = client.get(URL).data["data"]

        self.assertIsNone(data["business_name"])


class ProfileServiceTests(TestCase):

    def test_the_branch_row_is_created_lazily(self):
        user = UserFactory()
        profile = Profile.objects.create(
            user=user,
            account_type=AccountType.BUSINESS,
            full_name="X",
        )

        self.assertFalse(
            BusinessProfile.objects.filter(profile=profile).exists()
        )

        ProfileService().read(user)

        self.assertTrue(
            BusinessProfile.objects.filter(profile=profile).exists()
        )
