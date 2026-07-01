from __future__ import annotations

from dataclasses import dataclass, field

from taxsentry.runtime.session import RuntimeResponse

from .state import AgentMode
from .tool_registry import ToolResult


@dataclass
class AgentResponse:
    response: RuntimeResponse
    route: str
    mode: AgentMode
    tool: ToolResult | None = None
    hints: list[str] = field(default_factory=list)
    plan: str = ""
    toolchain: list[str] = field(default_factory=list)


AgentTurnResult = AgentResponse

