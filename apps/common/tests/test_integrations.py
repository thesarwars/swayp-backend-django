import pathlib
from decimal import Decimal

from django.test import SimpleTestCase

from integrations import (
    get_bank_data_provider,
    get_check_mail_provider,
    get_directory_provider,
    get_llm_provider,
    get_money_movement_provider,
)
from integrations.money_movement.base import STAGE_COMPLETED, TransferRequest
from integrations.money_movement.mock import MockMoneyMovementProvider

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


class FactoryTests(SimpleTestCase):

    def test_defaults_to_mock(self):
        self.assertIsInstance(
            get_money_movement_provider(), MockMoneyMovementProvider
        )
        for getter in (
            get_bank_data_provider,
            get_directory_provider,
            get_check_mail_provider,
            get_llm_provider,
        ):
            self.assertEqual(getter().name, "mock")


class MockMoneyMovementTests(SimpleTestCase):

    def test_execute_emits_stages_and_reference(self):
        provider = MockMoneyMovementProvider()
        result = provider.execute(
            TransferRequest(
                reference="SWP-20260115-0001",
                amount=Decimal("3200.00"),
                rail="ACH_STANDARD",
                source_token="mock-fs-4821",
                destination_token="mock-vendor-1",
            )
        )
        self.assertTrue(result.provider_reference.startswith("MOCK-"))
        self.assertEqual(result.status, "SUCCESSFUL")
        self.assertEqual(result.stages[-1].stage, STAGE_COMPLETED)

    def test_verify_returns_token_and_last4_only(self):
        provider = MockMoneyMovementProvider()
        v = provider.verify_bank_account(
            routing_number="021000021",
            account_number="000123454821",
            account_type="CHECKING",
        )
        self.assertEqual(v.last4, "4821")
        self.assertNotIn("000123454821", v.token)


class NoProcessorNameInSerializersTests(SimpleTestCase):
    """E1-S4 AC: no processor name reachable from any serializer."""

    BANNED = ("Moov", "Stripe", "Dwolla", "GoCardless")

    def test_serializers_free_of_processor_names(self):
        apps_dir = REPO_ROOT / "apps"
        offenders = []
        for path in apps_dir.rglob("*.py"):
            if "serializer" not in path.name and "serializers" not in str(path):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for name in self.BANNED:
                if name in text:
                    offenders.append(f"{path}: {name}")
        self.assertEqual(offenders, [], f"processor names leaked: {offenders}")
