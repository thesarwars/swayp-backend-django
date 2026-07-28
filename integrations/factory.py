"""Provider factory — resolves each domain to a concrete provider by setting.

Only mock providers are registered today; real providers (Plaid/Stripe/Moov/
Lob/Anthropic) register here as their epics land. Selecting an unregistered
provider raises a clear error rather than silently falling back.
"""

from django.conf import settings

from integrations.bank_data.mock import MockBankDataProvider
from integrations.check_mail.mock import MockCheckMailProvider
from integrations.directory.mock import MockDirectoryProvider
from integrations.llm.mock import MockLLMProvider
from integrations.messaging.django_email import DjangoEmailMessagingProvider
from integrations.messaging.mock import MockMessagingProvider
from integrations.money_movement.mock import MockMoneyMovementProvider

_REGISTRY = {
    "bank_data": {"mock": MockBankDataProvider},
    "money_movement": {"mock": MockMoneyMovementProvider},
    "directory": {"mock": MockDirectoryProvider},
    "check_mail": {"mock": MockCheckMailProvider},
    "llm": {"mock": MockLLMProvider},
    "messaging": {
        "mock": MockMessagingProvider,
        "django_email": DjangoEmailMessagingProvider,
    },
}

_SETTING = {
    "bank_data": "BANK_DATA_PROVIDER",
    "money_movement": "MONEY_MOVEMENT_PROVIDER",
    "directory": "DIRECTORY_PROVIDER",
    "check_mail": "CHECK_MAIL_PROVIDER",
    "llm": "LLM_PROVIDER",
    "messaging": "MESSAGING_PROVIDER",
}


def _resolve(domain: str):
    setting_key = _SETTING[domain]
    name = getattr(settings, setting_key, "mock") or "mock"
    providers = _REGISTRY[domain]
    if name not in providers:
        raise NotImplementedError(
            f"{domain} provider '{name}' is not implemented yet; "
            f"available: {sorted(providers)}. Set {setting_key}=mock."
        )
    return providers[name]()


def get_bank_data_provider():
    return _resolve("bank_data")


def get_money_movement_provider():
    return _resolve("money_movement")


def get_directory_provider():
    return _resolve("directory")


def get_check_mail_provider():
    return _resolve("check_mail")


def get_llm_provider():
    return _resolve("llm")


def get_messaging_provider():
    return _resolve("messaging")
