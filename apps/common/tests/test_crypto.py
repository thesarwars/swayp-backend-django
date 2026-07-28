from django.test import SimpleTestCase
from rest_framework import serializers

from apps.common.crypto import (
    EncryptedTextField,
    SensitiveCharField,
    mask_last4,
    reject_masked_value,
)


class MaskingTests(SimpleTestCase):

    def test_mask_last4(self):
        self.assertEqual(mask_last4("021540821"), "****0821")

    def test_mask_empty(self):
        self.assertEqual(mask_last4(""), "")
        self.assertEqual(mask_last4(None), "")

    def test_reject_masked_value(self):
        with self.assertRaises(serializers.ValidationError):
            reject_masked_value("****0821")
        self.assertEqual(reject_masked_value("021540821"), "021540821")


class _AchSerializer(serializers.Serializer):
    routing_number = SensitiveCharField(required=False)
    account_number = SensitiveCharField(required=False)


class SensitiveFieldTests(SimpleTestCase):

    def test_clean_value_accepted_and_write_only(self):
        s = _AchSerializer(data={"account_number": "021540821"})
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(
            s.validated_data["account_number"], "021540821"
        )
        # write_only -> never serialized back out
        self.assertNotIn("account_number", s.data)

    def test_masked_echo_rejected(self):
        s = _AchSerializer(data={"account_number": "****0821"})
        self.assertFalse(s.is_valid())
        self.assertIn("account_number", s.errors)

    def test_omitted_on_patch_is_unchanged(self):
        s = _AchSerializer(
            data={"routing_number": "021000021"}, partial=True
        )
        self.assertTrue(s.is_valid(), s.errors)
        # account_number simply absent -> caller leaves it unchanged
        self.assertNotIn("account_number", s.validated_data)


class EncryptedTextFieldTests(SimpleTestCase):

    def test_round_trip(self):
        field = EncryptedTextField()
        secret = "access-sandbox-abc123"
        ciphertext = field.get_prep_value(secret)
        self.assertNotEqual(ciphertext, secret)
        self.assertEqual(
            field.from_db_value(ciphertext, None, None), secret
        )

    def test_non_deterministic(self):
        field = EncryptedTextField()
        a = field.get_prep_value("same")
        b = field.get_prep_value("same")
        self.assertNotEqual(a, b)  # Fernet embeds a random IV
        self.assertEqual(field.from_db_value(a, None, None), "same")
        self.assertEqual(field.from_db_value(b, None, None), "same")

    def test_empty_passthrough(self):
        field = EncryptedTextField()
        self.assertIsNone(field.get_prep_value(None))
        self.assertEqual(field.get_prep_value(""), "")
