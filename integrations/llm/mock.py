from integrations.llm.base import LLMProvider, LLMResult


class MockLLMProvider(LLMProvider):
    """Deterministic echo — never calls a network, safe in tests/CI."""

    name = "mock"

    def complete(self, *, prompt, system=None, max_tokens=256) -> LLMResult:
        return LLMResult(
            text="[mock-llm] " + prompt.strip()[:max_tokens],
            model="mock",
        )
