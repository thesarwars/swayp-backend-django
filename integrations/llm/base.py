"""LLM provider interface (Anthropic Claude) — phrases Flo advice only.

The advisor's numbers are computed in Python; the LLM never produces the
authoritative figures, only the natural-language wording around them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str


class LLMProvider(ABC):
    name = "base"

    @abstractmethod
    def complete(
        self,
        *,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 256,
    ) -> LLMResult:
        ...
