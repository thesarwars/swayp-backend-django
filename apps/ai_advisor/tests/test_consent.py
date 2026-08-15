"""E7-S1 — consent, the service-level gate it drives, and its audit artifact."""

from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.ai_advisor.models import AdvisorConsent
from apps.ai_advisor.services.cash_context_service import CashContextService
from apps.ai_advisor.services.consent_service import ConsentService
from apps.ai_advisor.tests.support import SpyLLM
from apps.audit.models import AuditLog
from apps.banking.factories import BankAccountFactory, UserFactory
from apps.common.exceptions import BadRequestException

CONSENT_URL = "/api/v1/ai/consent"
CONSENT_TEXT = "I allow Flo to use my balances and bills for guidance."

_PROVIDER = "apps.ai_advisor.services.cash_context_service.get_llm_provider"


class ConsentServiceTests(TestCase):

    def setUp(self):
        self.user = UserFactory()

    def test_grant_files_the_client_ip_in_the_audit_trail(self):
        ConsentService.record(
            user=self.user, ip="203.0.113.9", user_agent="SwaypApp/1.0"
        )

        row = AuditLog.objects.get(action="ai_advisor.consent_granted")

        self.assertEqual(row.ip, "203.0.113.9")
        self.assertEqual(row.user_id, self.user.id)
        self.assertEqual(row.user_agent, "SwaypApp/1.0")

    def test_grant_is_refused_when_the_client_ip_is_unknown(self):
        """A consent record with a fabricated IP is worse than no record."""
        with self.assertRaises(BadRequestException):
            ConsentService.record(user=self.user, ip=None)

        self.assertFalse(AdvisorConsent.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_revoke_is_never_blocked_by_a_missing_ip(self):
        """Opting out must always be available, IP or no IP."""
        ConsentService.record(user=self.user, ip="203.0.113.9")

        consent = ConsentService.revoke(user=self.user, ip=None)

        self.assertIsNotNone(consent.revoked_at)
        self.assertFalse(ConsentService.has_live_consent(self.user))

        row = AuditLog.objects.get(action="ai_advisor.consent_revoked")
        self.assertIsNone(row.ip)

    def test_revoke_without_live_consent_is_a_noop(self):
        self.assertIsNone(
            ConsentService.revoke(user=self.user, ip="203.0.113.9")
        )

    def test_re_consent_after_revoke_is_live_again(self):
        ConsentService.record(user=self.user, ip="203.0.113.9")
        ConsentService.revoke(user=self.user, ip="203.0.113.9")
        ConsentService.record(user=self.user, ip="203.0.113.9")

        self.assertTrue(ConsentService.has_live_consent(self.user))
        self.assertEqual(AdvisorConsent.objects.count(), 1)

    def test_re_granting_live_consent_preserves_the_original_opt_in(self):
        first = ConsentService.record(user=self.user, ip="203.0.113.9")

        again = ConsentService.record(user=self.user, ip="203.0.113.9")

        self.assertEqual(again.consented_at, first.consented_at)
        self.assertEqual(
            AuditLog.objects.filter(
                action="ai_advisor.consent_granted"
            ).count(),
            1,
        )

    def test_state_reports_never_consented_without_a_row(self):
        state = ConsentService.state(self.user)

        self.assertFalse(state["is_live"])
        self.assertIsNone(state["consented_at"])
        self.assertIsNone(state["consent_text"])

    def test_state_reports_the_accepted_language(self):
        ConsentService.record(
            user=self.user, consent_text=CONSENT_TEXT, ip="203.0.113.9"
        )

        state = ConsentService.state(self.user)

        self.assertTrue(state["is_live"])
        self.assertEqual(state["consent_text"], CONSENT_TEXT)


@override_settings(FLO_LLM_ENABLED=True)
class RevokeStopsLLMCallsTests(TestCase):
    """E7-S1 AC2 — the gate is in the service and takes effect immediately."""

    def setUp(self):
        self.user = UserFactory()
        BankAccountFactory(
            connection__user=self.user,
            available_balance=Decimal("41200.00"),
            balance_as_of=timezone.now(),
        )
        self.spy = SpyLLM()

    def _build(self):
        with mock.patch(_PROVIDER, return_value=self.spy):
            return CashContextService().build(
                user=self.user, amount=Decimal("3200.00")
            )

    def test_revoking_stops_the_next_call_with_no_restart(self):
        ConsentService.record(user=self.user, ip="203.0.113.9")
        self._build()
        self.assertEqual(self.spy.calls, 1)

        ConsentService.revoke(user=self.user, ip="203.0.113.9")
        result = self._build()

        # Not "one more call that we ignored" — no call at all.
        self.assertEqual(self.spy.calls, 1)
        self.assertIn("Balance $41,200.00", result["text"])

    def test_no_consent_at_all_never_calls_the_provider(self):
        self._build()

        self.assertEqual(self.spy.calls, 0)


class ConsentAPITests(TestCase):

    def setUp(self):
        self.user = UserFactory()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_post_records_the_forwarded_client_not_the_proxy(self):
        response = self.client.post(
            CONSENT_URL,
            {"consent_text": CONSENT_TEXT},
            format="json",
            HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.7",
            REMOTE_ADDR="10.0.0.7",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["data"]["is_live"])

        row = AuditLog.objects.get(action="ai_advisor.consent_granted")
        self.assertEqual(row.ip, "203.0.113.9")

    def test_post_falls_back_to_remote_addr_without_a_proxy(self):
        self.client.post(
            CONSENT_URL,
            {"consent_text": CONSENT_TEXT},
            format="json",
            REMOTE_ADDR="198.51.100.4",
        )

        row = AuditLog.objects.get(action="ai_advisor.consent_granted")
        self.assertEqual(row.ip, "198.51.100.4")

    def test_delete_revokes_and_returns_the_record(self):
        self.client.post(CONSENT_URL, {"consent_text": CONSENT_TEXT}, format="json")

        response = self.client.delete(CONSENT_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["data"]["is_live"])

    def test_delete_with_nothing_live_returns_204(self):
        response = self.client.delete(CONSENT_URL)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_requires_authentication(self):
        response = APIClient().post(
            CONSENT_URL, {"consent_text": CONSENT_TEXT}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_blank_or_missing_consent_text_is_rejected(self):
        """The column is 'exact language shown' — a default is not that."""
        for payload in ({}, {"consent_text": ""}, {"consent_text": "   "}):
            with self.subTest(payload=payload):
                response = self.client.post(
                    CONSENT_URL, payload, format="json"
                )
                self.assertEqual(
                    response.status_code, status.HTTP_400_BAD_REQUEST
                )

        self.assertFalse(AdvisorConsent.objects.exists())

    def test_get_reads_state_without_granting_anything(self):
        response = self.client.get(CONSENT_URL)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["data"]["is_live"])
        self.assertFalse(AdvisorConsent.objects.exists())

        self.client.post(
            CONSENT_URL, {"consent_text": CONSENT_TEXT}, format="json"
        )
        state = self.client.get(CONSENT_URL).data["data"]

        self.assertTrue(state["is_live"])
        self.assertEqual(state["consent_text"], CONSENT_TEXT)

    def test_responses_use_the_project_envelope(self):
        response = self.client.post(
            CONSENT_URL, {"consent_text": CONSENT_TEXT}, format="json"
        )

        self.assertTrue(response.data["success"])
        self.assertIn("message", response.data)
        self.assertIn("data", response.data)
