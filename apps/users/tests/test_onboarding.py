"""Onboarding progress survives a drop-out (E2-S6).

Every onboarding screen says "Step n of 5", which promises that closing the
tab and coming back returns you to the same place. Nothing recorded it, so a
customer who stopped on the payment step had no way back and the client would
have had to guess by probing.

Progress is derived from what each step actually creates rather than stored as
a counter, so it cannot drift: connecting a bank from Settings completes step
4 just as the wizard would. The single exception is a deliberate skip, which
leaves no trace in the data and therefore has to be recorded.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.banking.factories import BankConnectionFactory
from apps.billing.services.subscription_service import SubscriptionService
from apps.users.models.business_profile import BusinessProfile
from apps.users.models.profile import AccountType, Profile
from apps.users.services.onboarding_service import OnboardingService
from apps.vendors.factories import UserFactory

URL = "/api/v1/users/onboarding/"
SKIP_URL = "/api/v1/users/onboarding/skip-bank/"


class OnboardingProgressTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        Profile.objects.create(
            user=self.user,
            account_type=AccountType.BUSINESS,
            full_name="Jane Smith",
        )
        self.service = OnboardingService()

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def state(self):
        return self.client.get(URL).data["data"]

    def complete_business(self):
        profile = Profile.objects.get(user=self.user)
        BusinessProfile.objects.update_or_create(
            profile=profile, defaults={"business_name": "Acme LLC"}
        )

    def test_a_fresh_account_starts_at_step_one(self):
        self.assertEqual(self.state()["current_step"], 1)

    def test_it_advances_as_each_step_is_done(self):
        self.complete_business()
        self.assertEqual(self.state()["current_step"], 2)

        SubscriptionService().subscribe(
            account=self.user, plan_code="FOUNDING"
        )
        # Founding has no trial, and the mock collects nothing, so step 3 is
        # satisfied by having a plan at all.
        self.assertEqual(self.state()["current_step"], 4)

    def test_a_trial_satisfies_the_payment_step(self):
        """The screen says "no card needed" — a trialling customer has
        finished that step without one."""
        self.complete_business()
        SubscriptionService().subscribe(
            account=self.user, plan_code="STANDARD"
        )

        steps = {s["key"]: s for s in self.state()["steps"]}

        self.assertTrue(steps["payment"]["complete"])

    def test_connecting_a_bank_completes_step_four(self):
        BankConnectionFactory(user=self.user)

        steps = {s["key"]: s for s in self.state()["steps"]}

        self.assertTrue(steps["bank"]["complete"])

    def test_a_bank_connected_outside_the_wizard_still_counts(self):
        """The reason this is derived. A stored counter would still say step
        4 was pending after connecting from Settings."""
        self.complete_business()
        SubscriptionService().subscribe(
            account=self.user, plan_code="FOUNDING"
        )
        BankConnectionFactory(user=self.user)

        state = self.state()

        self.assertTrue(state["complete"])
        self.assertIsNone(state["current_step"])

    def test_progress_survives_a_drop_out(self):
        """The whole point: sign out mid-wizard, come back, resume."""
        self.complete_business()
        SubscriptionService().subscribe(
            account=self.user, plan_code="FOUNDING"
        )

        fresh = APIClient()
        fresh.force_authenticate(user=self.user)

        self.assertEqual(fresh.get(URL).data["data"]["current_step"], 4)

    def test_the_declared_total_matches_the_progress_bar(self):
        state = self.state()

        self.assertEqual(state["total_steps"], 5)
        # Four are designed and served; the fifth has never been specified,
        # so it is declared rather than invented.
        self.assertEqual(state["designed_steps"], 4)


class SkipTests(TestCase):
    """"Skip for now" is the one thing that cannot be derived."""

    def setUp(self):
        self.user = UserFactory()
        Profile.objects.create(
            user=self.user,
            account_type=AccountType.BUSINESS,
            full_name="Jane Smith",
        )
        BusinessProfile.objects.create(
            profile=Profile.objects.get(user=self.user),
            business_name="Acme LLC",
        )
        SubscriptionService().subscribe(
            account=self.user, plan_code="FOUNDING"
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_skipping_the_bank_finishes_onboarding(self):
        self.assertEqual(
            self.client.get(URL).data["data"]["current_step"], 4
        )

        response = self.client.post(SKIP_URL, {}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["complete"])

    def test_a_skip_is_remembered_across_sessions(self):
        """Otherwise the wizard sends them back to a step they declined,
        every single sign-in."""
        self.client.post(SKIP_URL, {}, format="json")

        fresh = APIClient()
        fresh.force_authenticate(user=self.user)

        self.assertTrue(fresh.get(URL).data["data"]["complete"])

    def test_a_skipped_step_is_reported_as_skipped_not_done(self):
        """The UI should be able to offer it again later."""
        self.client.post(SKIP_URL, {}, format="json")

        steps = {
            s["key"]: s for s in self.client.get(URL).data["data"]["steps"]
        }

        self.assertTrue(steps["bank"]["skipped"])
        self.assertFalse(steps["bank"]["complete"])

    def test_connecting_after_skipping_marks_it_done(self):
        self.client.post(SKIP_URL, {}, format="json")
        BankConnectionFactory(user=self.user)

        steps = {
            s["key"]: s for s in self.client.get(URL).data["data"]["steps"]
        }

        self.assertTrue(steps["bank"]["complete"])


class IndividualAccountTests(TestCase):

    def test_the_business_step_never_blocks_an_individual(self):
        """They are never shown that screen, so it cannot be what is
        outstanding."""
        user = UserFactory()
        Profile.objects.create(
            user=user,
            account_type=AccountType.INDIVIDUAL,
            full_name="Sam Ortiz",
        )

        client = APIClient()
        client.force_authenticate(user=user)

        steps = {s["key"]: s for s in client.get(URL).data["data"]["steps"]}

        self.assertTrue(steps["business"]["complete"])


class AccountScopedTests(TestCase):
    """A team member sees the account's onboarding, not a private one."""

    def test_a_member_reads_the_accounts_progress(self):
        from apps.teams.factories import ActiveMemberFactory

        owner = UserFactory()
        Profile.objects.create(
            user=owner,
            account_type=AccountType.BUSINESS,
            full_name="Owner",
        )
        BusinessProfile.objects.create(
            profile=Profile.objects.get(user=owner),
            business_name="Acme LLC",
        )
        member = ActiveMemberFactory(account=owner)

        client = APIClient()
        client.force_authenticate(user=member.user)

        steps = {s["key"]: s for s in client.get(URL).data["data"]["steps"]}

        self.assertTrue(steps["business"]["complete"])

    def test_it_requires_authentication(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)
