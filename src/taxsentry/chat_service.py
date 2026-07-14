from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .events import AgentEvent, EventType
from .providers import create_provider
from .store import JobStore

SYSTEM = "Bạn là TaxSentry, trợ lý CFO và thuế Việt Nam. Xưng em, gọi người dùng là Sếp. Chỉ kết luận từ dữ liệu có thật, luôn nêu độ tin cậy và để Giám đốc quyết định cuối cùng."


class ChatService:
    """Shared chat runtime for the terminal and Control Center."""

    def __init__(self, settings: dict[str, Any], store: JobStore | None = None, provider_factory=create_provider):
        self.settings = settings
        self.store = store or JobStore()
        self.provider_factory = provider_factory
        self.provider = provider_factory(settings)
        self.session_id = self.store.create_session(settings["provider"]["kind"]) if hasattr(self.store, "create_session") else "terminal"
        self.history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]

    async def stream(self, text: str) -> AsyncIterator[AgentEvent]:
        self.history.append({"role": "user", "content": text})
        if hasattr(self.store, "add_message"):
            self.store.add_message(self.session_id, "user", text)
        chunks: list[str] = []
        async for event in self.provider.stream_turn(self.history):
            if event.type == EventType.TEXT_DELTA:
                chunks.append(event.text)
            yield event
        if chunks:
            content = "".join(chunks)
            self.history.append({"role": "assistant", "content": content})
            if hasattr(self.store, "add_message"):
                self.store.add_message(self.session_id, "assistant", content)

    async def switch_provider(self, kind: str) -> None:
        await self.provider.close()
        self.settings["provider"]["kind"] = kind
        self.settings["provider"]["auth_mode"] = kind
        self.provider = self.provider_factory(self.settings)

    def new_session(self) -> str:
        self.session_id = self.store.create_session(self.settings["provider"]["kind"]) if hasattr(self.store, "create_session") else "terminal"
        self.history[:] = [{"role": "system", "content": SYSTEM}]
        return self.session_id

    def clear(self) -> None:
        if hasattr(self.store, "clear_session"):
            self.store.clear_session(self.session_id)
        self.history[:] = [{"role": "system", "content": SYSTEM}]

    async def close(self) -> None:
        await self.provider.close()
