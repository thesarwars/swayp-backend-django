"""Third-party integrations behind interfaces (E1-S4).

Every money feature talks to these interfaces, never to a vendor SDK directly,
so the whole product runs on deterministic mocks with zero external accounts.
Concrete providers per BRD §5: bank_data=Plaid, money_movement=Stripe+Moov,
directory=Stripe-configured lookup, check_mail=Lob/PostGrid, llm=Anthropic.
Dwolla / GoCardless / Stripe-Treasury are excluded on record.
"""

from integrations.factory import (
    get_bank_data_provider,
    get_check_mail_provider,
    get_directory_provider,
    get_llm_provider,
    get_money_movement_provider,
)

__all__ = [
    "get_bank_data_provider",
    "get_check_mail_provider",
    "get_directory_provider",
    "get_llm_provider",
    "get_money_movement_provider",
]
