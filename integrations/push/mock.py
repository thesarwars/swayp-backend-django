"""Deterministic push provider — the default, and what tests run against.

Sends nothing. Two token shapes are given meaning so the failure paths can be
exercised without a Firebase project:

* a token containing ``"dead"`` comes back as rejected, which is how the
  deactivation path is tested,
* a token containing ``"fail"`` comes back as a transient failure, which must
  *not* deactivate anything.

Everything else succeeds. Without these, the only branch any test could reach
is the happy one, and the deactivation logic is precisely the part that goes
wrong quietly.
"""

from integrations.push.base import PushMessage, PushProvider, PushResult


class MockPushProvider(PushProvider):
    name = "mock"

    def send(self, message: PushMessage) -> PushResult:
        rejected = tuple(t for t in message.tokens if "dead" in t)
        failed = tuple(t for t in message.tokens if "fail" in t)
        sent = len(message.tokens) - len(rejected) - len(failed)

        return PushResult(
            sent=sent,
            failed=len(rejected) + len(failed),
            rejected_tokens=rejected,
            detail="mock",
        )
