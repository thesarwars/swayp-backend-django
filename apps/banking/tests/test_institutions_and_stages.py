"""The two screens the API could feed but not drive (plan §4.2, §4.3).

* **Select Your Bank** (1620-12323) had no endpoint at all.
* **Verifying / Scanning** (1620-12370, 1620-12434) drew four named stages
  against a model with three states, so the bar could only be a timer — and a
  timer advances whether or not anything is happening, which makes a stuck
  scan look exactly like a fast one.
"""

from django.test import TestCase, override_settings

from apps.banking.factories import (
    BankConnectionFactory,
    TransactionScanFactory,
    UserFactory,
)
from apps.banking.api.serializers.banking import TransactionScanSerializer
from apps.common.enums import ScanStatus
from rest_framework.test import APIClient

URL = "/api/v1/banking/institutions"


@override_settings(BANK_DATA_PROVIDER="mock")
class InstitutionSearchTests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_it_requires_authentication(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_a_query_matches_by_name(self):
        response = self.client.get(URL, {"search": "chase"})

        self.assertEqual(response.status_code, 200)
        names = [row["name"] for row in response.data["data"]]
        self.assertEqual(names, ["Chase Bank"])

    def test_the_match_is_case_insensitive(self):
        response = self.client.get(URL, {"search": "CHASE"})

        self.assertEqual(len(response.data["data"]), 1)

    def test_an_empty_query_returns_a_default_set(self):
        """The picker opens before anyone types."""
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.data["data"]), 1)

    def test_a_row_carries_what_the_screen_draws(self):
        row = self.client.get(URL, {"search": "chase"}).data["data"][0]

        for key in ("institution_id", "name", "logo", "subtitle"):
            self.assertIn(key, row)


class ScanStageTests(TestCase):

    def stages(self, **kwargs):
        scan = TransactionScanFactory(
            connection=BankConnectionFactory(), **kwargs
        )
        data = TransactionScanSerializer(scan).data

        return {s["key"]: s["status"] for s in data["progress"]["stages"]}

    def test_a_fresh_scan_is_active_at_the_history_step(self):
        """Connected and verified are facts by the time a scan exists."""
        stages = self.stages(
            status=ScanStatus.RUNNING, transactions_scanned=0, detected_count=0
        )

        self.assertEqual(stages["connected"], "done")
        self.assertEqual(stages["verifying"], "done")
        self.assertEqual(stages["history"], "active")
        self.assertEqual(stages["detecting"], "pending")

    def test_pulling_history_moves_the_active_step_on(self):
        stages = self.stages(
            status=ScanStatus.RUNNING, transactions_scanned=412,
            detected_count=0,
        )

        self.assertEqual(stages["history"], "done")
        self.assertEqual(stages["detecting"], "active")

    def test_a_finished_scan_has_every_step_done(self):
        stages = self.stages(
            status=ScanStatus.DONE, transactions_scanned=412, detected_count=17
        )

        self.assertEqual(set(stages.values()), {"done"})

    def test_a_failed_scan_shows_where_it_stopped(self):
        """Rather than every step done, or every step pending."""
        stages = self.stages(
            status=ScanStatus.FAILED, transactions_scanned=0, detected_count=0
        )

        self.assertEqual(stages["history"], "failed")
        self.assertEqual(stages["detecting"], "pending")

    def test_only_one_step_is_ever_active(self):
        for kwargs in (
            {"status": ScanStatus.RUNNING, "transactions_scanned": 0},
            {"status": ScanStatus.RUNNING, "transactions_scanned": 9},
        ):
            with self.subTest(**kwargs):
                stages = self.stages(detected_count=0, **kwargs)
                active = [k for k, v in stages.items() if v == "active"]

                self.assertEqual(len(active), 1)
