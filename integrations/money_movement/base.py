"""Money-movement provider interface (Stripe for configured-account vendors,
Moov for ACH). Plain-data DTOs only — no Django models cross this boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

# Stage names emitted during execution — consumed by E6 PaymentStage.
STAGE_AUTHORIZED = "AUTHORIZED"
STAGE_DEBITING = "DEBITING"
STAGE_ROUTING = "ROUTING"
STAGE_COMPLETED = "COMPLETED"
STAGE_FAILED = "FAILED"

# Per-stage status values (mirror PaymentStageStatus).
STATUS_PENDING = "PENDING"
STATUS_RUNNING = "RUNNING"
STATUS_DONE = "DONE"
STATUS_FAILED = "FAILED"


@dataclass(frozen=True)
class VerifiedBankAccount:
    """Result of provider-side tokenization: Swayp persists ONLY these."""

    token: str
    last4: str
    bank_name: str = ""


@dataclass(frozen=True)
class TransferRequest:
    reference: str
    amount: Decimal
    rail: str
    source_token: str
    destination_token: str
    idempotency_key: Optional[str] = None


@dataclass(frozen=True)
class StageEvent:
    stage: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class ProcessorResult:
    provider_reference: str
    status: str
    stages: tuple[StageEvent, ...] = field(default_factory=tuple)
    estimated_arrival: Optional[date] = None


class MoneyMovementProvider(ABC):
    name = "base"

    @abstractmethod
    def verify_bank_account(
        self,
        *,
        routing_number: str,
        account_number: str,
        account_type: str,
    ) -> VerifiedBankAccount:
        """Tokenize a raw bank account. Raw numbers never return to Swayp."""

    @abstractmethod
    def execute(self, transfer: TransferRequest) -> ProcessorResult:
        """Move money; emit ordered stage events."""
