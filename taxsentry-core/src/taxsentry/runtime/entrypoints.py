from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeEntrypointSpec:
    name: str
    mode: str
    argv: list[str]
    interactive: bool = True
    metadata: dict[str, Any] | None = None


ENTRYPOINT_MODE_MAP = {
    "start": ("interactive", True),
    "up": ("interactive", True),
    "dashboard": ("interactive", True),
    "bot": ("service", False),
    "telegram": ("service", False),
    "chat": ("conversation", True),
    "setup": ("configuration", True),
}


def normalize_entrypoint(name: str, argv: list[str] | None = None, *, metadata: dict[str, Any] | None = None) -> RuntimeEntrypointSpec:
    normalized = (name or "").strip().lower() or "start"
    mode, interactive = ENTRYPOINT_MODE_MAP.get(normalized, ("interactive", True))
    return RuntimeEntrypointSpec(
        name=normalized,
        mode=mode,
        argv=list(argv or []),
        interactive=interactive,
        metadata=metadata or {},
    )


__all__ = ["RuntimeEntrypointSpec", "normalize_entrypoint"]
