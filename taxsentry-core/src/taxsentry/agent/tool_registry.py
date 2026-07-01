from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ToolResult:
    name: str
    ok: bool
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


ToolHandler = Callable[..., ToolResult]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolHandler] = {}

    def register(self, name: str, handler: ToolHandler) -> None:
        self._tools[name] = handler

    def available(self) -> list[str]:
        return sorted(self._tools)

    def run(self, name: str, **kwargs: Any) -> ToolResult:
        handler = self._tools.get(name)
        if handler is None:
            return ToolResult(name=name, ok=False, output=f"Tool '{name}' is not registered.")

        try:
            result = handler(**kwargs)
        except Exception as exc:
            return ToolResult(name=name, ok=False, output=str(exc))

        if not isinstance(result, ToolResult):
            return ToolResult(
                name=name,
                ok=False,
                output=f"Tool '{name}' returned an invalid result.",
            )
        return result

