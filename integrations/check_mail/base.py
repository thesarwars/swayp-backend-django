"""Check print + mail provider interface (Lob / PostGrid)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class MailingAddress:
    legal_name: str
    street: str
    city: str
    state: str
    zip_code: str
    line2: str = ""


@dataclass(frozen=True)
class CheckRequest:
    reference: str
    amount: Decimal
    address: MailingAddress
    memo: str = ""
    expedited: bool = False


@dataclass(frozen=True)
class CheckResult:
    provider_reference: str
    status: str
    expected_delivery: Optional[date] = None


class CheckMailProvider(ABC):
    name = "base"

    @abstractmethod
    def verify_address(self, address: MailingAddress) -> bool:
        ...

    @abstractmethod
    def send_check(self, request: CheckRequest) -> CheckResult:
        ...
