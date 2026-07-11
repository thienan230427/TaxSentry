from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    TEXT_DELTA = "text_delta"
    REASONING = "reasoning"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_COMPLETED = "tool_completed"
    APPROVAL_REQUIRED = "approval_required"
    ERROR = "error"
    TURN_COMPLETED = "turn_completed"


@dataclass(slots=True)
class AgentEvent:
    type: EventType
    text: str = ""
    name: str = ""
    data: dict[str, Any] = field(default_factory=dict)
