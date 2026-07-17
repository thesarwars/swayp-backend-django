from integrations.money_movement.base import (
    STAGE_AUTHORIZED,
    STAGE_COMPLETED,
    STAGE_DEBITING,
    STAGE_ROUTING,
    STATUS_DONE,
    MoneyMovementProvider,
    ProcessorResult,
    StageEvent,
    TransferRequest,
    VerifiedBankAccount,
)


class MockMoneyMovementProvider(MoneyMovementProvider):
    """Deterministic: instant success, full stage progression."""

    name = "mock"

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
        stages = tuple(
            StageEvent(stage=s, status=STATUS_DONE)
            for s in (
                STAGE_AUTHORIZED,
                STAGE_DEBITING,
                STAGE_ROUTING,
                STAGE_COMPLETED,
            )
        )
        return ProcessorResult(
            provider_reference=f"MOCK-{transfer.reference}",
            status="SUCCESSFUL",
            stages=stages,
        )
