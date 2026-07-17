from integrations.check_mail.base import (
    CheckMailProvider,
    CheckRequest,
    CheckResult,
    MailingAddress,
)


class MockCheckMailProvider(CheckMailProvider):
    """Deterministic: every well-formed address verifies and mails."""

    name = "mock"

    def verify_address(self, address: MailingAddress) -> bool:
        return bool(
            address.legal_name
            and address.street
            and address.city
            and address.state
            and address.zip_code
        )

    def send_check(self, request: CheckRequest) -> CheckResult:
        return CheckResult(
            provider_reference=f"MOCK-CHK-{request.reference}",
            status="mailed",
            expected_delivery=None,
        )
