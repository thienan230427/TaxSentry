from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from taxsentry.runtime.policy import PolicyGate
from taxsentry.runtime.session import RuntimeResponse


@dataclass(frozen=True)
class ResponseEnvelope:
    text: str
    route: str
    confidence: float
    session_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


class ResponseComposer:
    """Compose a normalized response object from runtime output."""

    def __init__(self, policy_gate: PolicyGate | None = None):
        self.policy_gate = policy_gate or PolicyGate()

    def compose(
        self,
        text: str,
        *,
        route: str,
        confidence: float = 1.0,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeResponse:
        policy = self.policy_gate.evaluate(text)
        safe_text = policy.redacted_text
        envelope = ResponseEnvelope(
            text=safe_text,
            route=route,
            confidence=confidence,
            session_id=session_id,
            metadata={
                "policy_flags": policy.flags,
                "policy_reason": policy.reason,
                "created_at": datetime.now(timezone.utc).isoformat(),
                **(metadata or {}),
            },
        )
        return RuntimeResponse(
            text=envelope.text,
            route=envelope.route,
            confidence=envelope.confidence,
            session_id=envelope.session_id,
            metadata=envelope.metadata,
        )


__all__ = ["ResponseEnvelope", "ResponseComposer"]
