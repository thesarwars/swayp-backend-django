"""E7-S4 — the real LLM stays behind its flag, and its failures stay invisible."""

import datetime as dt
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai_advisor.services.cash_context_service import CashContextService
from apps.ai_advisor.services.consent_service import ConsentService
from apps.ai_advisor.tests.support import ExplodingLLM, FailingLLM, SpyLLM
from apps.banking.factories import BankAccountFactory, UserFactory
from apps.bills.factories import BillFactory, BillOccurrenceFactory

_PROVIDER = "apps.ai_advisor.services.cash_context_service.get_llm_provider"


class FloProviderTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user = UserFactory()
        self.account = BankAccountFactory(
            connection__user=self.user,
            available_balance=Decimal("10000.00"),
            balance_as_of=timezone.now(),
        )
        today = timezone.localdate()

        bill = BillFactory(
            user=self.user,
            amount=Decimal("389.00"),
            vendor__name="Verizon",
            anchor_date=today + dt.timedelta(days=5),
        )
        BillOccurrenceFactory(
            bill=bill,
            due_date=today + dt.timedelta(days=5),
            amount=Decimal("389.00"),
        )

        ConsentService.record(user=self.user, ip="203.0.113.9")

    def _build(self, provider):
        with mock.patch(_PROVIDER, return_value=provider):
            return CashContextService().build(
                user=self.user, amount=Decimal("3200.00")
            )

    @override_settings(FLO_LLM_ENABLED=False)
    def test_kill_switch_off_makes_no_call_even_with_live_consent(self):
        result = self._build(ExplodingLLM())

        self.assertIn("Balance $10,000.00", result["text"])

    @override_settings(FLO_LLM_ENABLED=True)
    def test_provider_failure_is_invisible_to_the_user(self):
        failing = FailingLLM()

        result = self._build(failing)

        self.assertEqual(failing.calls, 1)
        self.assertIn("Balance $10,000.00", result["text"])
        self.assertEqual(result["figures"]["balance_after"], Decimal("6800.00"))

    @override_settings(FLO_LLM_ENABLED=True)
    def test_outbound_payload_carries_no_account_identifiers(self):
        spy = SpyLLM()

        self._build(spy)

        prompt = spy.last_prompt
        self.assertIsNotNone(prompt)

        connection = self.account.connection
        for secret in (
            self.account.external_id,
            self.account.mask,
            connection.access_token,
            connection.item_id,
            str(self.user.id),
            self.user.email,
        ):
            self.assertNotIn(secret, prompt)

        # Only the aggregates the epic allows.
        self.assertIn("$10,000.00", prompt)

    @override_settings(FLO_LLM_ENABLED=True, FLO_LLM_DAILY_CAP=1)
    def test_daily_cap_stops_further_calls(self):
        spy = SpyLLM()

        self._build(spy)
        self._build(spy)

        self.assertEqual(spy.calls, 1)

    @override_settings(FLO_LLM_ENABLED=True, FLO_LLM_DAILY_CAP=3)
    def test_the_cap_window_does_not_slide_with_each_call(self):
        """The old get/set pair re-armed the 24 h expiry on every call.

        The TTL is written once, by ``add``. Counting afterwards must go
        through ``incr``, which leaves the expiry where it was — so a steady
        trickle of requests can no longer hold one day's window open forever.
        """
        spy = SpyLLM()
        key = CashContextService._cap_key(self.user)

        self._build(spy)

        with mock.patch.object(cache, "set") as set_spy:
            self._build(spy)

        self.assertFalse(set_spy.called)
        self.assertEqual(cache.get(key), 2)

    @override_settings(FLO_LLM_ENABLED=True, FLO_LLM_DAILY_CAP=2)
    def test_a_failed_call_does_not_consume_a_slot(self):
        # A missing API key raises before a packet leaves the process; that
        # must not burn the day's budget.
        self._build(FailingLLM())

        key = CashContextService._cap_key(self.user)
        self.assertEqual(cache.get(key, 0), 0)

        spy = SpyLLM()
        self._build(spy)
        self.assertEqual(spy.calls, 1)

    @override_settings(FLO_LLM_ENABLED=True, FLO_LLM_DAILY_CAP=0)
    def test_a_zero_cap_disables_the_provider(self):
        result = self._build(ExplodingLLM())

        self.assertIn("Balance $10,000.00", result["text"])

    @override_settings(FLO_LLM_ENABLED=True)
    def test_an_unreachable_cache_fails_closed(self):
        """If we cannot count the spend, we do not spend."""
        with mock.patch.object(
            cache, "add", side_effect=RuntimeError("redis is down")
        ):
            result = self._build(ExplodingLLM())

        self.assertIn("Balance $10,000.00", result["text"])


class AnthropicProviderTests(TestCase):
    """The flagged provider must not need its SDK until it is selected."""

    def test_module_imports_without_the_anthropic_package(self):
        from integrations.llm.anthropic import AnthropicLLMProvider

        self.assertEqual(AnthropicLLMProvider.name, "anthropic")

    @override_settings(ANTHROPIC_API_KEY="")
    def test_missing_key_raises_before_any_client_is_built(self):
        from integrations.llm.anthropic import AnthropicLLMProvider

        with self.assertRaises(Exception):
            AnthropicLLMProvider().complete(prompt="hello")

    def test_factory_default_is_the_offline_template_provider(self):
        from integrations.factory import get_llm_provider

        self.assertEqual(get_llm_provider().name, "template")

    def test_anthropic_client_is_built_inside_the_p95_budget(self):
        """E7-S2 AC3: 2.5 s p95, so no retry multiplier on the timeout."""
        import integrations.llm.anthropic as anthropic_module

        built = {}

        class _Client:
            def __init__(self, **kwargs):
                built.update(kwargs)
                self.messages = self

            def create(self, **kwargs):
                class _Block:
                    type = "text"
                    text = "ok"

                return type("R", (), {"content": [_Block()]})()

        fake_sdk = type("anthropic", (), {"Anthropic": _Client})

        with mock.patch.dict(
            "sys.modules", {"anthropic": fake_sdk}
        ), override_settings(
            ANTHROPIC_API_KEY="sk-test", FLO_LLM_TIMEOUT_SECONDS=2.0
        ):
            anthropic_module.AnthropicLLMProvider().complete(prompt="hi")

        self.assertEqual(built["timeout"], 2.0)
        self.assertEqual(built["max_retries"], 0)


class TemplateProviderTests(TestCase):

    def test_it_returns_the_sentence_unchanged(self):
        from integrations.llm.template import TemplateLLMProvider

        sentence = "Balance $10,000.00. After this payment you'll have..."
        result = TemplateLLMProvider().complete(prompt=sentence)

        self.assertEqual(result.text, sentence)

    def test_the_mock_echo_is_what_it_exists_to_avoid(self):
        """Guards the reason template.py is separate from mock.py."""
        from integrations.llm.mock import MockLLMProvider

        self.assertIn(
            "[mock-llm]", MockLLMProvider().complete(prompt="x").text
        )
