"""Anthropic Claude provider for Flo phrasing (E7-S4).

Active only when ``LLM_PROVIDER=anthropic``. The SDK is imported lazily inside
``complete`` so the module (and ``manage.py check``) load fine without the
``anthropic`` package installed — enabling this provider in production is a
"pip install anthropic + set the key" step. Any failure here propagates so
the caller (CashContextService) can fall back to the template; the advisor
never surfaces a provider error to the user.
"""

from __future__ import annotations

from django.conf import settings

from integrations.llm.base import LLMProvider, LLMResult

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_TIMEOUT_SECONDS = 8


class AnthropicLLMProvider(LLMProvider):
    name = "anthropic"

    def complete(self, *, prompt, system=None, max_tokens=256) -> LLMResult:
        import anthropic  # lazy: only needed when this provider is selected

        api_key = getattr(settings, "ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

        model = getattr(settings, "LLM_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL

        client = anthropic.Anthropic(
            api_key=api_key, timeout=DEFAULT_TIMEOUT_SECONDS
        )

        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )

        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", "") == "text"
        )

        return LLMResult(text=text, model=model)
