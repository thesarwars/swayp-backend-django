"""No-raw-storage utilities (E1-S6).

BRD §3.4: raw routing/account numbers are **never stored** — not even encrypted.
Swayp keeps only a masked last-4 + a provider token. This module provides:

- ``mask_last4`` / ``masked_representation`` — the "…1234 everywhere" display.
- ``reject_masked_value`` + ``SensitiveCharField`` — write-only input that
  rejects masked echoes ("****1234") and, on PATCH, treats an omitted field as
  unchanged (standard DRF partial behaviour — the field simply isn't required).
- ``EncryptedTextField`` — reversible field encryption for **provider secrets
  only** (e.g. a Plaid ``access_token``). It must NOT be used for bank numbers;
  those never touch a model field — they go straight to the money-movement
  provider, which returns ``{token, last4, bank_name}`` (see TokenizedBankAccount).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from rest_framework import serializers

MASK_CHAR = "*"


# --- Masking --------------------------------------------------------------

def mask_last4(value: str | None, visible: int = 4, width: int = 4) -> str:
    """Return a masked representation exposing only the last ``visible`` chars.

    ``mask_last4("021540821")`` -> ``"****0821"``. Non-digits are ignored for
    length purposes but the raw is never echoed.
    """
    if not value:
        return ""
    digits = "".join(ch for ch in str(value) if ch.isalnum())
    last = digits[-visible:]
    return f"{MASK_CHAR * width}{last}"


def masked_representation(value: str | None) -> str:
    return mask_last4(value)


def reject_masked_value(value: str) -> str:
    """Reject a value that looks like a masked echo (contains ``*``)."""
    if value and MASK_CHAR in value:
        raise serializers.ValidationError(
            "Provide the full value, not the masked one."
        )
    return value


class SensitiveCharField(serializers.CharField):
    """Write-only char field that rejects masked (``*``-containing) input.

    Omitted on PATCH -> not in ``validated_data`` -> caller leaves it unchanged.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("write_only", True)
        kwargs.setdefault("trim_whitespace", True)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        return reject_masked_value(value)


# --- Tokenization contract ------------------------------------------------

@dataclass(frozen=True)
class TokenizedBankAccount:
    """What the money-movement provider returns for a raw bank account.

    Swayp persists ONLY these fields — never the raw routing/account number.
    """

    token: str
    last4: str
    bank_name: str = ""


# --- Field-level encryption (provider secrets ONLY) -----------------------

def _get_field_cipher():
    keys = getattr(settings, "FIELD_ENCRYPTION_KEYS", None) or []
    if not keys:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEYS is not configured; cannot use "
            "EncryptedTextField."
        )
    from cryptography.fernet import Fernet, MultiFernet

    # First key encrypts; all keys can decrypt (supports rotation).
    return MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])


class EncryptedTextField(models.TextField):
    """TextField transparently encrypted at rest via Fernet (MultiFernet).

    For provider secrets/tokens only. Values are non-deterministically
    encrypted, so equality lookups on this field will not match — fetch the
    owning row by id, never by the encrypted value.
    """

    description = "Text encrypted at rest (provider secrets only)"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return _get_field_cipher().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        from cryptography.fernet import InvalidToken

        try:
            return _get_field_cipher().decrypt(value.encode()).decode()
        except InvalidToken:
            # Value was stored plaintext (pre-encryption) or key rotated out.
            return value
