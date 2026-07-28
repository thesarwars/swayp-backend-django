"""Offline phrasing provider — the default (E7-S2).

The advisor's sentence is already written, in Python, by
``CashContextService._template``. This provider hands it back unchanged, which
makes "no LLM configured" an ordinary provider rather than a special case and
lets the feature ship with no LLM account at all.

Deliberately not ``mock.py``: that one prefixes its echo with "[mock-llm] " so
a test can prove the provider was reached, which is exactly the string that
must never appear in front of a user. Shipping the mock as the default meant
one flipped kill switch away from serving it.
"""

from __future__ import annotations

from integrations.llm.base import LLMProvider, LLMResult


class TemplateLLMProvider(LLMProvider):
    name = "template"

    def complete(self, *, prompt, system=None, max_tokens=256) -> LLMResult:
        return LLMResult(text=prompt, model="template")
