"""Shared doubles for the Flo suite.

The LLM is always a local double here — no test may reach a network, which is
the property E7-S4 AC1 asserts and every other test relies on silently.
"""

from integrations.llm.base import LLMResult


class SpyLLM:
    """Records calls and echoes the prompt back, so phrasing round-trips."""

    name = "spy"

    def __init__(self, text=None):
        self.calls = 0
        self.prompts = []
        self._text = text

    def complete(self, *, prompt, system=None, max_tokens=256):
        self.calls += 1
        self.prompts.append(prompt)

        return LLMResult(
            text=self._text if self._text is not None else prompt,
            model="spy",
        )

    @property
    def last_prompt(self):
        return self.prompts[-1] if self.prompts else None


class ExplodingLLM:
    """Fails the test if it is called at all."""

    name = "exploding"

    def complete(self, *, prompt, system=None, max_tokens=256):
        raise AssertionError(
            "The LLM provider was called when no call was permitted."
        )


class FailingLLM:
    """Models a provider outage — timeout, 429, 500, anything."""

    name = "failing"

    def __init__(self):
        self.calls = 0

    def complete(self, *, prompt, system=None, max_tokens=256):
        self.calls += 1
        raise RuntimeError("provider is down")
