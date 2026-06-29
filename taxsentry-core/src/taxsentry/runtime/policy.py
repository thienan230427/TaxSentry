from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    risk_level: str
    redacted_text: str
    flags: list[str] = field(default_factory=list)
    reason: str = ""


class PolicyGate:
    """Simple privacy / safety gate for runtime text."""

    _PATTERNS = [
        re.compile(r"(?i)\b(api[_ -]?key|token|password|app password|secret)\b\s*[:=]\s*\S+"),
        re.compile(r"(?i)bearer\s+[a-z0-9\-._~+/]+=*"),
    ]

    def redact(self, text: str) -> str:
        redacted = text
        for pattern in self._PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    def evaluate(self, text: str) -> PolicyDecision:
        flags: list[str] = []
        risk_level = "low"
        reason = ""

        redacted_text = self.redact(text)
        if redacted_text != text:
            flags.append("sensitive-data")
            risk_level = "high"
            reason = "Sensitive value was detected and redacted."

        lowered = text.lower()
        if any(keyword in lowered for keyword in ("password", "token", "secret", "api key", "app password")):
            flags.append("sensitive-keyword")
            risk_level = "high"
            if not reason:
                reason = "Sensitive keywords detected."

        allowed = risk_level != "high" or bool(redacted_text)
        return PolicyDecision(
            allowed=allowed,
            risk_level=risk_level,
            redacted_text=redacted_text,
            flags=flags,
            reason=reason,
        )
