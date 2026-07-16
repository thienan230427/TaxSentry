from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from .events import AgentEvent, EventType
from .providers import create_provider
from .store import JobStore

SYSTEM = "Bạn là TaxSentry, trợ lý CFO và thuế Việt Nam. Xưng em, gọi người dùng là Sếp. Chỉ kết luận từ dữ liệu có thật, luôn nêu độ tin cậy và để Giám đốc quyết định cuối cùng. Gmail và việc tạo file do ứng dụng xử lý; không yêu cầu cài plugin email hay tự nhận đã tạo/gửi file."


class ChatService:
    """One chat session shared by the terminal and Telegram."""

    def __init__(self, settings: dict[str, Any], store: JobStore | None = None, provider_factory=create_provider):
        self.settings = settings
        self.store = store or JobStore()
        self.provider_factory = provider_factory
        self.provider = provider_factory(settings)
        self.session_id = self.store.create_session(settings["provider"]["kind"]) if hasattr(self.store, "create_session") else "terminal"
        self.history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]
        self._turn_lock = asyncio.Lock()

    async def stream(self, text: str, *, source: str = "terminal", context: str = "") -> AsyncIterator[AgentEvent]:
        async with self._turn_lock:
            self.history.append({"role": "user", "content": text})
            if hasattr(self.store, "add_message"):
                self.store.add_message(self.session_id, "user", text)
            if source != "terminal" and hasattr(self.store, "event"):
                self.store.event(None, "chat_source", {"session_id": self.session_id, "source": source})
            chunks: list[str] = []
            messages = self.history if not context else [*self.history[:-1], {"role": "user", "content": f"{text}\n\n{context}"}]
            try:
                async with asyncio.timeout(float(self.settings["worker"].get("analysis_timeout_seconds", 300))):
                    async for event in self.provider.stream_turn(messages):
                        if event.type == EventType.TEXT_DELTA:
                            chunks.append(event.text)
                        yield event
            except TimeoutError:
                await self._reset_provider()
                yield AgentEvent(EventType.ERROR, text="Provider quá thời gian 5 phút và đã được khởi động lại.")
                return
            except Exception as exc:
                await self._reset_provider()
                yield AgentEvent(EventType.ERROR, text=str(exc))
                return
            if chunks:
                content = "".join(chunks)
                self.history.append({"role": "assistant", "content": content})
                if hasattr(self.store, "add_message"):
                    self.store.add_message(self.session_id, "assistant", content)

    async def structured(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        async with self._turn_lock:
            chunks: list[str] = []
            try:
                async with asyncio.timeout(float(self.settings["worker"].get("analysis_timeout_seconds", 300))):
                    async for event in self.provider.stream_turn(
                        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                        output_schema=schema,
                    ):
                        if event.type == EventType.TEXT_DELTA:
                            chunks.append(event.text)
                        elif event.type == EventType.ERROR:
                            raise RuntimeError(event.text)
            except Exception:
                await self._reset_provider()
                raise
            text = "".join(chunks)
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Provider did not return structured JSON")
            return json.loads(text[start : end + 1])

    async def _reset_provider(self) -> None:
        try:
            await self.provider.close()
        finally:
            self.provider = self.provider_factory(self.settings)

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
        if hasattr(self.store, "close"):
            self.store.close()
