from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class AgentMode(str, Enum):
    CHAT = "chat"
    ANALYZE = "analysis"
    EXECUTE = "execute"
    REVIEW = "review"
    SETUP = "setup"


@dataclass(frozen=True)
class ProviderPreset:
    key: str
    label: str
    description: str
    kind: str
    base_url: str
    model: str
    auth_mode: str
    api_key: str = ""
    available: bool = True
    badge: str = ""


@dataclass
class SurfaceEvent:
    kind: str
    title: str
    detail: str = ""
    status: str = "info"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AgentSurfaceState:
    mode: AgentMode = AgentMode.CHAT
    provider_key: str = "lmstudio"
    session_id: str = ""
    last_route: str = "chat"
    last_plan: str = ""
    last_toolchain: list[str] = field(default_factory=list)
    last_progress: str = ""
    last_user_input: str = ""
    last_response: str = ""
    last_tool_name: str = ""
    last_tool_status: str = ""
    last_error: str = ""
    recent_events: list[SurfaceEvent] = field(default_factory=list)

    def push_event(self, event: SurfaceEvent, *, limit: int = 12) -> None:
        self.recent_events.append(event)
        if len(self.recent_events) > limit:
            self.recent_events = self.recent_events[-limit:]


def _codex_available() -> bool:
    return (Path.home() / ".codex" / "auth.json").exists()


def build_provider_presets(settings: dict[str, Any]) -> list[ProviderPreset]:
    provider = settings.get("provider") or {}
    active_model = str(provider.get("model") or "google/gemma-4-e4b")
    active_url = str(provider.get("base_url") or "http://localhost:1234/v1")
    active_key = str(provider.get("kind") or "lmstudio")

    return [
        ProviderPreset(
            key="lmstudio",
            label="LM Studio",
            description="Local desktop app with built-in model server",
            kind="lmstudio",
            base_url=active_url if active_key == "lmstudio" else "http://localhost:1234/v1",
            model=active_model if active_key == "lmstudio" else "google/gemma-4-e4b",
            auth_mode="lmstudio",
            api_key=str(provider.get("api_key") or ""),
            available=True,
            badge="local",
        ),
        ProviderPreset(
            key="codex_oauth",
            label="OpenAI / Codex OAuth",
            description="Reuse Codex login or direct OpenAI API",
            kind="codex_oauth",
            base_url="https://api.openai.com/v1",
            model=active_model if active_key == "codex_oauth" else "gpt-4.1",
            auth_mode="codex_oauth",
            available=_codex_available(),
            badge="oauth",
        ),
        ProviderPreset(
            key="custom",
            label="Custom endpoint",
            description="Any OpenAI-compatible provider",
            kind="custom",
            base_url=active_url if active_key == "custom" else "https://api.openai.com/v1",
            model=active_model if active_key == "custom" else "gpt-4.1-mini",
            auth_mode="api_key",
            api_key=str(provider.get("api_key") or ""),
            available=True,
            badge="flex",
        ),
    ]
