from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .state import AgentMode


@dataclass(frozen=True)
class AgentRequest:
    text: str
    sanitized_text: str
    route: str
    mode: AgentMode
    session_id: str
    context: dict[str, Any] = field(default_factory=dict)
    hints: list[str] = field(default_factory=list)

