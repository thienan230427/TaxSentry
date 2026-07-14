from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from taxsentry.bot import telegram_bot
from taxsentry.chat_service import ChatService
from taxsentry.cockpit import COMMANDS, Cockpit, SlashCompleter, banner_text
from taxsentry.events import AgentEvent, EventType


def settings(**overrides):
    value = {
        "configured": True,
        "provider": {"kind": "lmstudio", "model": "local"},
        "gmail": {"enabled": False},
        "telegram": {"enabled": False},
        "worker": {"poll_seconds": 60},
    }
    value.update(overrides)
    return value


class FakeProvider:
    def __init__(self):
        self.closed = False

    async def stream_turn(self, messages):
        yield AgentEvent(EventType.TEXT_DELTA, text="Xin chào Sếp")
        yield AgentEvent(EventType.TURN_COMPLETED)

    async def close(self):
        self.closed = True


class FakeStore:
    def __init__(self):
        self.job = {"id": "job-123456", "state": "needs_review"}
        self.requeued = []

    def resolve(self, prefix=""):
        return self.job

    def requeue(self, job_id, *, approved=False):
        self.requeued.append((job_id, approved))

    def recent_jobs(self, limit=10):
        return [{**self.job, "subject": "Báo cáo", "retries": 0}]

    def latest_report(self):
        return {"payload": {"executive_summary": "Doanh thu ổn định"}}

    def create_session(self, provider):
        return "abcd-session"

    def add_message(self, *args):
        pass

    def event(self, *args):
        pass

    def clear_session(self, *args):
        pass

    def close(self):
        pass


class FakePrompt:
    def __init__(self, **kwargs):
        self.app = SimpleNamespace(invalidate=lambda: None)


def test_banner_is_responsive_and_has_ascii_fallback():
    full = banner_text(settings(gmail={"enabled": True}, telegram={"enabled": True}), 120)
    medium = banner_text(settings(), 80)
    narrow = banner_text(settings(), 60)
    ascii_banner = banner_text(settings(), 120, unicode=False)
    assert len(full.splitlines()) == 4 and "╔╦╗" in full and "Telegram" in full
    assert len(medium.splitlines()) == 3 and medium.startswith("◆ TAXSENTRY")
    assert narrow == "◆ TAXSENTRY · FINANCIAL SENTINEL"
    assert ascii_banner == "TAXSENTRY · FINANCIAL SENTINEL"


def test_slash_palette_filters_commands_and_shows_description():
    results = list(SlashCompleter().get_completions(Document("/gm"), CompleteEvent(completion_requested=True)))
    assert [item.text for item in results] == ["/gmail"]
    assert "Hộp thư" in str(results[0].display_meta)


@pytest.mark.asyncio
async def test_cockpit_commands_are_compact(monkeypatch):
    provider, store, output = FakeProvider(), FakeStore(), []
    monkeypatch.setattr("taxsentry.cockpit.JobStore", lambda: store)
    monkeypatch.setattr("taxsentry.cockpit.PromptSession", FakePrompt)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda value: provider)
    monkeypatch.setattr("taxsentry.cockpit.describe_config", lambda value: "configured")
    cockpit = Cockpit(settings())
    cockpit.console = SimpleNamespace(print=lambda *args, **kwargs: output.append(args[0] if args else ""))
    for command in ("/help", "/status", "/jobs", "/report", "/retry job", "/approve job", "/new", "/unknown"):
        await cockpit._command(command)
    assert list(COMMANDS) == ["/help", "/status", "/gmail", "/jobs", "/report", "/retry", "/approve", "/new", "/exit"]
    assert store.requeued == [("job-123456", False), ("job-123456", True)]
    assert "configured" in output and "Doanh thu ổn định" in output


@pytest.mark.asyncio
async def test_chat_service_serializes_terminal_and_telegram_turns():
    active = 0
    overlaps = []

    class Provider(FakeProvider):
        async def stream_turn(self, messages):
            nonlocal active
            active += 1
            overlaps.append(active)
            await asyncio.sleep(0.01)
            yield AgentEvent(EventType.TEXT_DELTA, text=messages[-1]["content"])
            active -= 1

    store = FakeStore()
    chat = ChatService(settings(), store=store, provider_factory=lambda value: Provider())

    async def consume(text, source):
        return [event async for event in chat.stream(text, source=source)]

    await asyncio.gather(consume("terminal", "terminal"), consume("telegram", "telegram:42"))
    assert overlaps == [1, 1]
    assert [item["content"] for item in chat.history if item["role"] == "user"] == ["terminal", "telegram"]


@pytest.mark.asyncio
async def test_gmail_context_reaches_model_but_not_persistent_history():
    seen = []

    class Provider(FakeProvider):
        async def stream_turn(self, messages):
            seen.append(messages[-1]["content"])
            yield AgentEvent(EventType.TEXT_DELTA, text="Đã đọc")

    chat = ChatService(settings(), store=FakeStore(), provider_factory=lambda value: Provider())
    _ = [event async for event in chat.stream("Gmail hôm nay có gì?", context="UID: 42\nUntrusted body")]
    assert "UID: 42" in seen[0]
    assert [item["content"] for item in chat.history if item["role"] == "user"] == ["Gmail hôm nay có gì?"]


@pytest.mark.asyncio
async def test_exit_closes_provider_without_background_services(monkeypatch):
    provider = FakeProvider()

    class ExitPrompt(FakePrompt):
        async def prompt_async(self, *args, **kwargs):
            return "/exit"

    monkeypatch.setattr("taxsentry.cockpit.JobStore", FakeStore)
    monkeypatch.setattr("taxsentry.cockpit.PromptSession", lambda **kwargs: ExitPrompt())
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda value: provider)
    monkeypatch.setattr("taxsentry.cockpit.patch_stdout", lambda **kwargs: nullcontext())
    cockpit = Cockpit(settings())
    cockpit._header = lambda: None
    assert await cockpit.run() == 0 and provider.closed


@pytest.mark.asyncio
async def test_telegram_uses_allowlist_and_shared_chat(monkeypatch):
    import telegram.ext

    replies, handlers, sources = [], [], []

    class App:
        def add_handler(self, handler):
            handlers.append(handler)

    class Builder:
        def token(self, token): return self
        def build(self): return App()

    class Application:
        @staticmethod
        def builder(): return Builder()

    class Chat:
        async def stream(self, text, *, source):
            sources.append(source)
            yield AgentEvent(EventType.TEXT_DELTA, text="Đã nhận")

    monkeypatch.setattr(telegram.ext, "Application", Application)
    monkeypatch.setattr(telegram.ext, "CommandHandler", lambda name, callback: (name, callback))
    monkeypatch.setattr(telegram.ext, "MessageHandler", lambda filters, callback: ("chat", callback))
    monkeypatch.setattr(telegram_bot, "load_config", lambda: {"director": {"telegram_chat_ids": [42]}})
    monkeypatch.setattr(telegram_bot, "JobStore", FakeStore)
    monkeypatch.setattr(telegram_bot, "get_secret", lambda name: "token")
    telegram_bot.build_application(Chat())
    callback = handlers[-1][1]

    async def reply_text(text): replies.append(text)

    await callback(SimpleNamespace(effective_chat=SimpleNamespace(id=7), message=SimpleNamespace(text="x", reply_text=reply_text)), None)
    await callback(SimpleNamespace(effective_chat=SimpleNamespace(id=42), message=SimpleNamespace(text="x", reply_text=reply_text)), None)
    assert replies == ["Đã nhận"] and sources == ["telegram:42"]
