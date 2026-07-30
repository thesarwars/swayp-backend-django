"""ABA routing validation (E3-S9)."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.banking.services.routing_service import (
    RoutingValidationService,
    has_valid_checksum,
    normalize,
)
from apps.users.models import User


class ChecksumTests(TestCase):

    def test_known_good_routing_numbers_pass(self):
        for routing in ["021000021", "121000248", "026009593", "091000019"]:
            with self.subTest(routing=routing):
                self.assertTrue(has_valid_checksum(routing))

    def test_a_single_digit_change_fails(self):
        self.assertTrue(has_valid_checksum("021000021"))
        self.assertFalse(has_valid_checksum("021000022"))

    def test_wrong_length_fails(self):
        for routing in ["", "1234", "0210000210"]:
            with self.subTest(routing=routing):
                self.assertFalse(has_valid_checksum(routing))

    def test_normalize_strips_formatting(self):
        self.assertEqual(normalize("026-009-593"), "026009593")
        self.assertEqual(normalize(" 021 000 021 "), "021000021")


class ServiceTests(TestCase):

    def setUp(self):
        self.service = RoutingValidationService()

    def test_valid_known_bank(self):
        result = self.service.validate("021000021")

        self.assertTrue(result["valid"])
        self.assertTrue(result["aba_verified"])
        self.assertTrue(result["bank_known"])
        self.assertEqual(result["bank_name"], "JPMorgan Chase Bank")
        self.assertIn("ABA verified", result["message"])

    def test_valid_but_unknown_bank(self):
        # Valid checksum, valid prefix, absent from the local directory.
        result = self.service.validate("011000015")

        self.assertTrue(result["valid"])
        self.assertTrue(result["aba_verified"])
        self.assertFalse(result["bank_known"])
        self.assertIsNone(result["bank_name"])

    def test_bad_checksum_is_reported(self):
        result = self.service.validate("021000022")

        self.assertFalse(result["valid"])
        self.assertIn("checksum", result["message"].lower())

    def test_bad_prefix_is_reported(self):
        result = self.service.validate("999000000")

        self.assertFalse(result["valid"])
        self.assertIn("prefix", result["message"].lower())

    def test_empty_is_reported(self):
        self.assertFalse(self.service.validate("")["valid"])

    def test_formatting_is_tolerated(self):
        self.assertTrue(self.service.validate("026-009-593")["valid"])


class EndpointTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="routing@example.com", password="Sw@yp-Test-1"
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_valid_number_returns_the_bank(self):
        response = self.client.post(
            "/api/v1/banking/routing/validate/",
            {"routing_number": "021000021"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["data"]["valid"])
        self.assertEqual(
            response.data["data"]["bank_name"], "JPMorgan Chase Bank"
        )

    def test_the_routing_number_is_never_echoed_back(self):
        response = self.client.post(
            "/api/v1/banking/routing/validate/",
            {"routing_number": "021000021"},
            format="json",
        )

        self.assertNotIn("021000021", str(response.data))

    def test_a_masked_value_is_rejected(self):
        response = self.client.post(
            "/api/v1/banking/routing/validate/",
            {"routing_number": "*****0021"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_authentication_is_required(self):
        response = APIClient().post(
            "/api/v1/banking/routing/validate/",
            {"routing_number": "021000021"},
            format="json",
        )

        self.assertEqual(response.status_code, 401)
