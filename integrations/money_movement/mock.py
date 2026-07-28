"""Deterministic money-movement mock (E1-S4 / E6-S7).

Scenarios are driven by the transfer amount, so a test can ask for a specific
outcome without patching anything:

- amount ending in .01  -> NSF failure, with the balance at the attempt
- amount ending in .02  -> ambiguous: the transfer IS submitted, then the call
                           raises. This is the crash-mid-call case the
                           execution engine has to recover from by lookup
                           rather than by re-sending.
- anything else         -> instant success

Submitted transfers are remembered by idempotency key so ``lookup`` can report
what actually happened.
"""

from decimal import Decimal

from integrations.money_movement.base import (
    STAGE_AUTHORIZED,
    STAGE_COMPLETED,
    STAGE_DEBITING,
    STAGE_FAILED,
    STAGE_ROUTING,
    STATUS_DONE,
    STATUS_FAILED,
    MoneyMovementProvider,
    ProcessorResult,
    StageEvent,
    TransferRequest,
    VerifiedBankAccount,
)

NSF_CENTS = Decimal("0.01")
AMBIGUOUS_CENTS = Decimal("0.02")


class AmbiguousProcessorError(Exception):
    """The transfer was submitted but the outcome was never received."""


def _cents(amount):
    return Decimal(amount).quantize(Decimal("0.01")) % Decimal("1.00")


_SUCCESS_STAGES = tuple(
    StageEvent(stage=stage, status=STATUS_DONE)
    for stage in (
        STAGE_AUTHORIZED,
        STAGE_DEBITING,
        STAGE_ROUTING,
        STAGE_COMPLETED,
    )
)

_FAILURE_STAGES = (
    StageEvent(stage=STAGE_AUTHORIZED, status=STATUS_DONE),
    StageEvent(stage=STAGE_DEBITING, status=STATUS_FAILED, detail="NSF"),
    StageEvent(stage=STAGE_FAILED, status=STATUS_FAILED, detail="NSF"),
)


class MockMoneyMovementProvider(MoneyMovementProvider):

    name = "mock"

    #: Class-level so it survives across service instances in a process, which
    #: is what makes the lookup-after-crash path testable.
    _submitted = {}

    @classmethod
    def reset(cls):
        cls._submitted = {}

    def verify_bank_account(
        self, *, routing_number, account_number, account_type
    ) -> VerifiedBankAccount:
        last4 = str(account_number)[-4:]

        return VerifiedBankAccount(
            token=f"mock-fs-{last4}",
            last4=last4,
            bank_name="Mock Bank",
        )

    def execute(self, transfer: TransferRequest) -> ProcessorResult:
        result = self._outcome(transfer)

        if transfer.idempotency_key:
            # Recorded before returning, so an ambiguous call still leaves the
            # trace that lookup needs.
            self._submitted[transfer.idempotency_key] = result

        if _cents(transfer.amount) == AMBIGUOUS_CENTS:
            raise AmbiguousProcessorError(
                "submitted, but the response was lost"
            )

        return result

    def _outcome(self, transfer):
        reference = f"MOCK-{transfer.reference}"

        if _cents(transfer.amount) == NSF_CENTS:
            return ProcessorResult(
                provider_reference=reference,
                status="FAILED",
                stages=_FAILURE_STAGES,
                failure_reason="NSF",
                failure_detail={
                    "available_balance": "2180.00",
                    "attempted_amount": str(transfer.amount),
                    "processor_message": "Insufficient funds",
                },
            )

        return ProcessorResult(
            provider_reference=reference,
            status="SUCCESSFUL",
            stages=_SUCCESS_STAGES,
        )

    def lookup(self, *, idempotency_key):
        return self._submitted.get(idempotency_key)

    def void(self, *, reference):
        return True
