from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from .events import AgentEvent, EventType
from .memory import MemoryService, SessionService, trusted_source
from .prompt import IMMUTABLE_SAFETY, PromptAssembler, prompt_hash, safe_company_id
from .providers import create_provider
from .security import redact_secrets
from .store import JobStore, runtime_store

# Kept as a compatibility import for integrations that previously imported SYSTEM.
SYSTEM = IMMUTABLE_SAFETY
_CRITICAL_CONTEXT = re.compile(
    r"source_id|citation|evidenceref|missing_data|assumption|"
    r"quyết\s+định|decision|chưa\s+hoàn\s+tất|pending|todo",
    re.IGNORECASE,
)


class ChatService:
    """One scoped, persistent chat session shared by the terminal and Telegram."""

    def __init__(
        self,
        settings: dict[str, Any],
        store: JobStore | None = None,
        provider_factory=create_provider,
    ):
        self.settings = settings
        self.store = store or runtime_store(settings)
        self.provider_factory = provider_factory
        self.provider = provider_factory(settings)
        self.company_id = safe_company_id(
            str(
                settings.get("agent", {}).get("company_id")
                or settings.get("advisor", {}).get("company", {}).get("id")
                or "default"
            )
        )
        self.prompt_assembler = PromptAssembler(settings)
        self.memory = MemoryService(self.store, settings, home=self.prompt_assembler.home)
        self.sessions = SessionService(self.store)
        self.system_prompt = self.prompt_assembler.build(company_id=self.company_id)
        self.session_summary = ""
        self.session_id = self._create_session()
        self.history: list[dict[str, str]] = [{"role": "system", "content": self.system_prompt}]
        self._turn_lock = asyncio.Lock()

    async def stream(
        self,
        text: str,
        *,
        source: str = "terminal",
        context: str = "",
    ) -> AsyncIterator[AgentEvent]:
        async with self._turn_lock:
            safe_text = redact_secrets(text)
            self.history.append({"role": "user", "content": safe_text})
            self._archive_message("user", safe_text, source=source, trusted=trusted_source(source))
            if source != "terminal" and hasattr(self.store, "event"):
                self.store.event(None, "chat_source", {"session_id": self.session_id, "source": source})
            self._compact_history()
            chunks: list[str] = []
            messages = [
                *self.history[:-1],
                {"role": "user", "content": self._turn_payload(safe_text, context)},
            ]
            try:
                timeout = float(self.settings.get("worker", {}).get("analysis_timeout_seconds", 300))
                async with asyncio.timeout(timeout):
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
                content = redact_secrets("".join(chunks))
                self.history.append({"role": "assistant", "content": content})
                self._archive_message("assistant", content, source=source, trusted=True)
                if hasattr(self.store, "save_memory"):
                    self.memory.record_turn(
                        text,
                        content,
                        company_id=self.company_id,
                        source=source,
                    )
            self._save_provider_thread()

    async def structured(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        async with self._turn_lock:
            chunks: list[str] = []
            try:
                timeout = float(self.settings.get("worker", {}).get("analysis_timeout_seconds", 300))
                async with asyncio.timeout(timeout):
                    async for event in self.provider.stream_turn(
                        [
                            {"role": "system", "content": self.system_prompt},
                            {"role": "user", "content": prompt},
                        ],
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
            self._save_provider_thread()
            return json.loads(text[start : end + 1])

    def resume_session(self, session_id: str) -> str:
        session = self.sessions.resume(session_id, company_id=self.company_id)
        self.session_id = session_id
        self.system_prompt = self.prompt_assembler.build(session, self.company_id)
        self.session_summary = str(session.get("summary") or "")
        self.history = [
            {"role": "system", "content": self.system_prompt},
            *[
                {"role": str(message["role"]), "content": str(message["content"])}
                for message in session["messages"]
            ],
        ]
        self._reset_provider_thread()
        self._compact_history()
        return session_id

    def search_sessions(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.sessions.search(query, company_id=self.company_id, limit=limit)

    def reload_prompt(self) -> str:
        self.system_prompt = self.prompt_assembler.build(company_id=self.company_id)
        self.history[0] = {"role": "system", "content": self.system_prompt}
        if hasattr(self.store, "update_session_prompt"):
            self.store.update_session_prompt(
                self.session_id,
                self.system_prompt,
                prompt_hash(self.system_prompt),
            )
        self._reset_provider_thread()
        return prompt_hash(self.system_prompt)

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
        self.system_prompt = self.prompt_assembler.build(company_id=self.company_id)
        self.session_summary = ""
        self.session_id = self._create_session()
        self.history[:] = [{"role": "system", "content": self.system_prompt}]
        self._reset_provider_thread()
        return self.session_id

    def clear(self) -> None:
        # Clearing starts a fresh session so the previous conversation remains archived.
        self.new_session()

    async def close(self) -> None:
        await self.provider.close()
        if hasattr(self.store, "close"):
            self.store.close()

    def _create_session(self) -> str:
        if not hasattr(self.store, "create_session"):
            return "terminal"
        provider = str(self.settings.get("provider", {}).get("kind", "lmstudio"))
        model = str(self.settings.get("provider", {}).get("model", ""))
        try:
            return self.store.create_session(
                provider,
                platform="shared",
                company_id=self.company_id,
                model=model,
                system_prompt=self.system_prompt,
                system_prompt_hash=prompt_hash(self.system_prompt),
            )
        except TypeError:
            return self.store.create_session(provider)

    def _archive_message(self, role: str, content: str, *, source: str, trusted: bool) -> None:
        if not hasattr(self.store, "add_message"):
            return
        try:
            self.store.add_message(
                self.session_id,
                role,
                content,
                company_id=self.company_id,
                source=source,
                trusted=trusted,
                expires_at=self._message_expiry(),
            )
        except TypeError:
            self.store.add_message(self.session_id, role, content)

    def _turn_payload(self, text: str, context: str) -> str:
        sections = [text]
        if hasattr(self.store, "memory_items"):
            items = self.memory.search(text, company_id=self.company_id, limit=8)
            if items:
                sections.append(
                    "<RETRIEVED_MEMORY>\n"
                    + "\n".join(f"- {item['content']}" for item in items)
                    + "\n</RETRIEVED_MEMORY>"
                )
        if self.session_summary and not getattr(self.provider, "thread_id", ""):
            sections.append(f"<SESSION_SUMMARY>\n{self.session_summary}\n</SESSION_SUMMARY>")
        if context:
            sections.append(self.prompt_assembler.untrusted_context(redact_secrets(context)))
        return "\n\n".join(sections)

    def _compact_history(self) -> None:
        memory = self.settings.get("memory", {})
        window = max(4_000, int(memory.get("context_window_chars", 80_000)))
        soft_ratio = float(memory.get("soft_context_ratio", 0.55))
        hard_ratio = float(memory.get("hard_context_ratio", 0.80))
        if not 0 < soft_ratio < hard_ratio <= 1:
            soft_ratio, hard_ratio = 0.55, 0.80
        soft, hard = window * soft_ratio, window * hard_ratio
        total = sum(len(message["content"]) for message in self.history)
        if total < soft:
            return
        max_turns = max(2, int(memory.get("max_turns", 12)))
        body = self.history[1:]
        keep = (
            min(max_turns, max(2, len(body) // 2))
            if total >= hard
            else max_turns * 2
        )
        if len(body) <= keep:
            return
        older, recent = body[:-keep], body[-keep:]
        # ponytail: deterministic excerpts avoid another model call; use semantic summaries if recall tests demand it.
        summary = self._summary(older, max_chars=max(1_000, int(window * 0.15)))
        self.session_summary = summary
        self.history[:] = [
            self.history[0],
            {"role": "system", "content": f"SESSION SUMMARY\n{summary}"},
            *recent,
        ]
        if hasattr(self.store, "update_session_summary"):
            self.store.update_session_summary(self.session_id, summary)

    @staticmethod
    def _summary(messages: list[dict[str, str]], *, max_chars: int) -> str:
        excerpts = []
        critical = []
        for message in messages:
            content = " ".join(message["content"].split())
            excerpts.append(f"[{message['role']}] {content[:800]}")
            for match in _CRITICAL_CONTEXT.finditer(content):
                start, end = max(0, match.start() - 200), match.end() + 600
                item = f"[critical:{message['role']}] {content[start:end]}"
                if item not in critical:
                    critical.append(item)
                if len(critical) >= 20:
                    break
        critical_text = "\n".join(critical)
        summary = "\n".join(
            part
            for part in (
                f"IMPORTANT CONTEXT\n{critical_text}" if critical_text else "",
                "EARLIER EXCERPTS\n" + "\n".join(excerpts),
            )
            if part
        )
        if len(summary) > max_chars:
            critical_budget = min(len(critical_text), max_chars * 2 // 3)
            critical_part = critical_text[:critical_budget]
            remaining = max_chars - len(critical_part) - 48
            excerpt_part = "\n".join(excerpts)[-max(0, remaining) :]
            summary = (
                "IMPORTANT CONTEXT\n"
                + critical_part
                + "\n[Earlier excerpts omitted]\n"
                + excerpt_part
            )[-max_chars:]
        return summary

    def _message_expiry(self) -> str:
        days = int(self.settings.get("memory", {}).get("retention_days", 90))
        return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    def _reset_provider_thread(self) -> None:
        if hasattr(self.provider, "thread_id"):
            self.provider.thread_id = ""
        if hasattr(self.store, "set_session_provider_thread"):
            self.store.set_session_provider_thread(self.session_id, "")

    def _save_provider_thread(self) -> None:
        if hasattr(self.store, "set_session_provider_thread"):
            self.store.set_session_provider_thread(
                self.session_id,
                str(getattr(self.provider, "thread_id", "")),
            )
