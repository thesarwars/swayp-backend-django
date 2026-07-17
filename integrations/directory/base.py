"""Vendor-directory provider interface (configured-account lookup)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DirectoryVendor:
    external_id: str
    name: str
    category: str
    verified: bool
    speed: str = ""


class DirectoryProvider(ABC):
    name = "base"

    @abstractmethod
    def search(self, *, query: str) -> tuple[DirectoryVendor, ...]:
        ...
