"""Registration accepts what the Create Account screen actually sends.

The screen asks for first name, last name, business email, business name,
industry, business size, a password and three checkboxes — and nothing else.
This endpoint used to require a postal address, a phone number, a billing
address and a point of contact on top, none of which the screen has a field
for, so a client built to the design could not register at all.

The four are optional now and are collected later by onboarding Step 1 and
Settings, which is the right order anyway: asking for a billing address before
the customer has chosen a plan never made sense.

Both payload shapes are tested. The old one still has to work — clients built
against it are in the wild.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models.business_profile import BusinessProfile
from apps.users.models.individual_profile import IndividualProfile
from apps.users.models.profile import AccountType, Profile
from apps.users.models.user import User

URL = "/api/v1/auth/register"

PASSWORD = "Str0ng!Passphrase1"

#: Exactly the fields on the Create Account screen, and nothing else.
DESIGN_PAYLOAD = {
    "first_name": "Jane",
    "last_name": "Smith",
    "email": "jane@acme.com",
    "business_name": "Acme Corporation, LLC",
    "industry": "Construction",
    "business_size": "11-50",
    "password": PASSWORD,
    "confirm_password": PASSWORD,
    "terms_accepted": True,
    "signatory_confirmed": True,
    "marketing_opt_in": False,
}

#: What clients sent before the screen existed.
LEGACY_PAYLOAD = {
    "account_type": "BUSINESS",
    "full_name": "Dana Reed",
    "address": "1 Old Street",
    "email": "dana@reed.com",
    "phone_number": "+14155552671",
    "password": PASSWORD,
    "confirm_password": PASSWORD,
    "business_name": "Reed Trading LLC",
    "poc_name": "Dana Reed",
    "billing_address": "1 Old Street",
}


class DesignPayloadTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def register(self, **overrides):
        payload = {**DESIGN_PAYLOAD, **overrides}

        return self.client.post(URL, payload, format="json")

    def test_the_screens_payload_registers(self):
        """The whole point. This used to fail on four missing fields."""
        response = self.register()

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(User.objects.filter(email="jane@acme.com").exists())

    def test_the_split_name_becomes_the_full_name(self):
        self.register()
        profile = Profile.objects.get(user__email="jane@acme.com")

        self.assertEqual(profile.full_name, "Jane Smith")

    def test_the_user_row_carries_the_split_name(self):
        """The dashboard greeting and the Stripe customer read these."""
        self.register()
        user = User.objects.get(email="jane@acme.com")

        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.last_name, "Smith")

    def test_industry_and_business_size_are_stored(self):
        """The screen collects them and there was nowhere to put them."""
        self.register()
        branch = BusinessProfile.objects.get(
            profile__user__email="jane@acme.com"
        )

        self.assertEqual(branch.industry, "Construction")
        self.assertEqual(branch.business_size, "11-50")

    def test_it_defaults_to_a_business_account(self):
        """The screen says "Business accounts only" and sends no type."""
        self.register()
        profile = Profile.objects.get(user__email="jane@acme.com")

        self.assertEqual(profile.account_type, AccountType.BUSINESS)

    def test_poc_defaults_to_the_person_signing_up(self):
        """Not on the screen. Defaulting to the signatory is true, and better
        than refusing a signup over it."""
        self.register()
        branch = BusinessProfile.objects.get(
            profile__user__email="jane@acme.com"
        )

        self.assertEqual(branch.poc_name, "Jane Smith")

    def test_the_omitted_fields_are_blank_not_invented(self):
        self.register()
        profile = Profile.objects.get(user__email="jane@acme.com")

        self.assertFalse(profile.address)
        self.assertFalse(profile.business.billing_address)


class ConsentCaptureTests(TestCase):
    """The screen's two required checkboxes are legal artifacts."""

    def setUp(self):
        self.client = APIClient()

    def test_acceptance_is_recorded_with_a_timestamp(self):
        """"Did they accept, and when" has to be answerable later, and a
        boolean answers only half of it."""
        self.client.post(URL, DESIGN_PAYLOAD, format="json")
        profile = Profile.objects.get(user__email="jane@acme.com")

        self.assertIsNotNone(profile.terms_accepted_at)
        self.assertIsNotNone(profile.signatory_confirmed_at)

    def test_an_unticked_box_records_nothing_rather_than_a_falsehood(self):
        payload = {
            **DESIGN_PAYLOAD,
            "terms_accepted": False,
            "signatory_confirmed": False,
        }
        self.client.post(URL, payload, format="json")
        profile = Profile.objects.get(user__email="jane@acme.com")

        self.assertIsNone(profile.terms_accepted_at)
        self.assertIsNone(profile.signatory_confirmed_at)

    def test_the_marketing_box_is_a_preference_not_a_consent_record(self):
        payload = {**DESIGN_PAYLOAD, "marketing_opt_in": True}
        self.client.post(URL, payload, format="json")

        self.assertTrue(
            Profile.objects.get(
                user__email="jane@acme.com"
            ).marketing_opt_in
        )


class PhoneOptionalTests(TestCase):
    """phone_number is unique and nullable, which is a trap."""

    def setUp(self):
        self.client = APIClient()

    def test_two_accounts_can_register_without_a_phone(self):
        """Writing "" instead of None would let the first succeed and collide
        every one after it, because Postgres allows many NULLs but only one
        empty string in a unique column."""
        first = self.client.post(URL, DESIGN_PAYLOAD, format="json")
        second = self.client.post(
            URL,
            {**DESIGN_PAYLOAD, "email": "sam@acme.com"},
            format="json",
        )

        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(second.status_code, 201, second.data)

    def test_a_phone_less_account_stores_null_not_blank(self):
        self.client.post(URL, DESIGN_PAYLOAD, format="json")

        self.assertIsNone(
            User.objects.get(email="jane@acme.com").phone_number
        )

    def test_a_duplicate_phone_is_still_refused(self):
        self.client.post(URL, LEGACY_PAYLOAD, format="json")

        response = self.client.post(
            URL,
            {
                **LEGACY_PAYLOAD,
                "email": "other@reed.com",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("phone_number", response.data["errors"])


class LegacyPayloadTests(TestCase):
    """Clients built against the old contract are in the wild."""

    def setUp(self):
        self.client = APIClient()

    def test_the_old_payload_still_registers(self):
        response = self.client.post(URL, LEGACY_PAYLOAD, format="json")

        self.assertEqual(response.status_code, 201, response.data)

    def test_full_name_alone_is_still_accepted(self):
        self.client.post(URL, LEGACY_PAYLOAD, format="json")
        profile = Profile.objects.get(user__email="dana@reed.com")

        self.assertEqual(profile.full_name, "Dana Reed")

    def test_full_name_is_split_onto_the_user_row(self):
        self.client.post(URL, LEGACY_PAYLOAD, format="json")
        user = User.objects.get(email="dana@reed.com")

        self.assertEqual(user.first_name, "Dana")
        self.assertEqual(user.last_name, "Reed")

    def test_an_individual_account_still_works(self):
        payload = {
            **LEGACY_PAYLOAD,
            "account_type": "INDIVIDUAL",
            "email": "solo@example.com",
            "phone_number": "+14155552672",
        }
        response = self.client.post(URL, payload, format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(
            IndividualProfile.objects.filter(
                profile__user__email="solo@example.com"
            ).exists()
        )


class StillRequiredTests(TestCase):
    """Loosening the schema must not loosen what actually matters."""

    def setUp(self):
        self.client = APIClient()

    def test_a_business_still_needs_a_name(self):
        payload = {k: v for k, v in DESIGN_PAYLOAD.items()}
        payload.pop("business_name")

        response = self.client.post(URL, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("business_name", response.data["errors"])

    def test_a_name_is_required_in_one_form_or_the_other(self):
        payload = {k: v for k, v in DESIGN_PAYLOAD.items()}
        payload.pop("first_name")
        payload.pop("last_name")

        response = self.client.post(URL, payload, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("full_name", response.data["errors"])

    def test_the_password_rules_are_unchanged(self):
        response = self.client.post(
            URL,
            {**DESIGN_PAYLOAD, "password": "short", "confirm_password": "short"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data["errors"])

    def test_mismatched_passwords_are_still_refused(self):
        response = self.client.post(
            URL,
            {**DESIGN_PAYLOAD, "confirm_password": PASSWORD + "x"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_a_duplicate_email_is_still_refused(self):
        self.client.post(URL, DESIGN_PAYLOAD, format="json")
        response = self.client.post(URL, DESIGN_PAYLOAD, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data["errors"])


class OnboardingCollectsTheRestTests(TestCase):
    """What registration stopped demanding, Settings must be able to set —
    onboarding Step 1 says "You can update these details anytime in Settings"."""

    def setUp(self):
        self.client = APIClient()
        self.client.post(URL, DESIGN_PAYLOAD, format="json")
        self.user = User.objects.get(email="jane@acme.com")

        self.auth = APIClient()
        self.auth.force_authenticate(user=self.user)

    def test_step_one_fields_can_be_set_afterwards(self):
        response = self.auth.patch(
            "/api/v1/users/profile",
            {
                "trading_name": "Acme",
                "business_type": "LLC",
                "website": "https://acme.com",
                "ein": "12-3456789",
                "billing_address": "1 Acme Way",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)

        branch = BusinessProfile.objects.get(profile__user=self.user)
        self.assertEqual(branch.trading_name, "Acme")
        self.assertEqual(branch.ein, "12-3456789")
        self.assertEqual(branch.billing_address, "1 Acme Way")

    def test_what_registration_captured_is_readable(self):
        data = self.auth.get("/api/v1/users/profile").data["data"]

        self.assertEqual(data["business_name"], "Acme Corporation, LLC")
        self.assertEqual(data["industry"], "Construction")
        self.assertEqual(data["business_size"], "11-50")
