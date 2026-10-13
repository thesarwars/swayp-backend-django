"""BANK-8 — a detected bill can be corrected before it is imported.

The review screen says "You can edit any detail". The edit lands on the
candidate, and import turns the candidate into the bill, so the bill gets
what the user corrected.
"""

from decimal import Decimal

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.banking.models import BillDetectionCandidate
from apps.banking.services.scan_service import ScanService
from apps.bill_categories.models import BillCategory
from apps.bills.models.bill import Bill
from apps.vendors.factories import UserFactory


@override_settings(BANK_DATA_PROVIDER="mock")
class CandidateEditTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        BillCategory.objects.get_or_create(
            name="Other",
            defaults={"icon": "https://e.com/i.png", "color": "#111"},
        )[0]
        self.utilities = BillCategory.objects.create(
            name="Utilities", icon="https://e.com/u.png", color="#222"
        )

        with self.captureOnCommitCallbacks(execute=True):
            exchange = self.client.post(
                "/api/v1/banking/link/exchange",
                {"public_token": "public-mock-chase", "consent_accepted": True},
                format="json",
            )

        self.scan_id = exchange.json()["data"]["scan"]["id"]
        self.candidate = BillDetectionCandidate.objects.filter(
            scan_id=self.scan_id
        ).first()

    def _url(self, candidate_id=None):
        return (
            f"/api/v1/banking/scans/{self.scan_id}/candidates/"
            f"{candidate_id or self.candidate.id}"
        )

    def _patch(self, body, **kwargs):
        return self.client.patch(self._url(**kwargs), body, format="json")

    def test_an_edit_is_what_the_imported_bill_gets(self):
        response = self._patch(
            {
                "amount": "410.50",
                "category": str(self.utilities.id),
                "cadence": "QUARTERLY",
                "due_day": 20,
            }
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["amount"], "410.50")
        self.assertEqual(data["category_guess_name"], "Utilities")

        self.client.post(
            f"/api/v1/banking/scans/{self.scan_id}/import",
            {"candidate_ids": [str(self.candidate.id)]},
            format="json",
        )

        bill = Bill.objects.get(detection_candidates=self.candidate)
        self.assertEqual(bill.amount, Decimal("410.50"))
        self.assertEqual(bill.category, self.utilities)
        self.assertEqual(bill.frequency, "QUARTERLY")
        self.assertEqual(bill.anchor_date.day, 20)

    def test_partial_edit_leaves_the_rest(self):
        before = (self.candidate.cadence, self.candidate.due_day)

        self._patch({"amount": "1.00"})

        self.candidate.refresh_from_db()
        self.assertEqual(self.candidate.amount, Decimal("1.00"))
        self.assertEqual((self.candidate.cadence, self.candidate.due_day), before)

    def test_an_imported_candidate_cannot_be_edited(self):
        self.client.post(
            f"/api/v1/banking/scans/{self.scan_id}/import",
            {"all": True},
            format="json",
        )

        response = self._patch({"amount": "1.00"})

        self.assertEqual(response.status_code, 400)

    def test_weekly_due_day_is_a_weekday(self):
        self.assertEqual(
            self._patch({"cadence": "WEEKLY", "due_day": 15}).status_code, 400
        )
        self.assertEqual(
            self._patch({"cadence": "WEEKLY", "due_day": 5}).status_code, 200
        )

    def test_switching_to_weekly_checks_the_existing_due_day(self):
        self.candidate.due_day = 15
        self.candidate.save(update_fields=["due_day"])

        self.assertEqual(self._patch({"cadence": "WEEKLY"}).status_code, 400)

    def test_invalid_values_are_refused(self):
        for body in (
            {},
            {"amount": "0"},
            {"due_day": 32},
            {"cadence": "YEARLY"},
            {"category": "00000000-0000-0000-0000-000000000000"},
        ):
            with self.subTest(body=body):
                self.assertEqual(self._patch(body).status_code, 400)

    def test_another_accounts_candidate_is_not_found(self):
        stranger = APIClient()
        stranger.force_authenticate(user=UserFactory())

        response = stranger.patch(self._url(), {"amount": "1.00"}, format="json")

        self.assertEqual(response.status_code, 404)
        self.candidate.refresh_from_db()
        self.assertNotEqual(self.candidate.amount, Decimal("1.00"))


class CategoryGuessPreferenceTests(TestCase):
    """``_CATEGORY_HINTS`` names categories in preference order.

    The lookup used ``filter(name__in=...).first()``, which applies the
    model's ordering (display_order, name) rather than the order the hint
    declares, so the preference never took effect: once the seeded "Rent"
    existed with a lower display_order than a "Commercial Rent" added later,
    a WeWork charge was filed under the general category while the specific
    one sat unused.
    """

    def setUp(self):
        self.service = ScanService()

    def test_the_specific_category_wins_over_the_general_one(self):
        BillCategory.objects.get_or_create(
            name="Rent",
            defaults={"icon": "", "color": "#111", "display_order": 1},
        )
        specific, _ = BillCategory.objects.get_or_create(
            name="Commercial Rent",
            defaults={"icon": "", "color": "#222", "display_order": 90},
        )

        self.assertEqual(
            self.service.guess_category("WeWork 123").id, specific.id
        )

    def test_the_general_category_is_used_when_it_is_the_only_one(self):
        general, _ = BillCategory.objects.get_or_create(
            name="Rent",
            defaults={"icon": "", "color": "#111", "display_order": 1},
        )
        BillCategory.objects.filter(name="Commercial Rent").delete()

        self.assertEqual(
            self.service.guess_category("WeWork 123").id, general.id
        )

    def test_an_unmatched_vendor_gets_no_category(self):
        self.assertIsNone(self.service.guess_category("Totally Unknown Ltd"))
