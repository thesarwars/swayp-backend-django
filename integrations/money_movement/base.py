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
    # Populated on failure. failure_detail carries whatever the processor can
    # tell us — for NSF that includes the balance at the time of the attempt,
    # which the resolution screen shows the user (E6-S6).
    failure_reason: str = ""
    failure_detail: dict = field(default_factory=dict)


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

    def lookup(self, *, idempotency_key: str) -> Optional[ProcessorResult]:
        """Outcome of a previous attempt, or None if the key is unknown.

        The recovery path for an ambiguous failure: a worker that died after
        submitting must be able to learn what happened instead of re-sending.
        Providers that cannot support this return None, and the payment is
        left for a human.
        """
        return None

    def void(self, *, reference: str) -> bool:
        """Cancel a submitted transfer, if the processor still can."""
        return False
