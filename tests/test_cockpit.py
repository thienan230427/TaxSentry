from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from textual.widgets import Markdown, Static

from taxsentry.bot import telegram_bot
from taxsentry.chat_service import ChatService
from taxsentry.cockpit import (
    COMMANDS,
    Cockpit,
    Composer,
    SlashCompleter,
    ToolCard,
    ToolOverlay,
    banner_text,
    redact,
    safe_text,
    tool_text,
)
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


def test_banner_is_responsive_and_has_ascii_fallback():
    full = banner_text(settings(gmail={"enabled": True}, telegram={"enabled": True}), 120)
    medium = banner_text(settings(), 80)
    narrow = banner_text(settings(), 60)
    ascii_banner = banner_text(settings(), 120, unicode=False)
    assert full.startswith("◆ TAXSENTRY") and "lmstudio/local" in full
    assert medium.startswith("◆ TAXSENTRY") and narrow.startswith("◆ TAXSENTRY")
    assert ascii_banner.startswith("* TAXSENTRY")


def test_slash_palette_filters_commands_and_shows_description():
    assert SlashCompleter.matches("/gm") == ["/gmail"]


def test_tool_output_is_redacted_and_bounded():
    preview, full, truncated = tool_text({"token": "secret", "output": "x" * 5000})
    assert "secret" not in full and "[REDACTED]" in full
    assert truncated and len(preview) < len(full)
    assert redact({"nested": {"api_key": "bad"}})["nested"]["api_key"] == "[REDACTED]"
    assert redact({"API-Key": "bad"})["API-Key"] == "[REDACTED]"
    assert safe_text("safe\x1b[31m red\x00") == "safe red"


@pytest.mark.asyncio
async def test_cockpit_commands_are_compact(monkeypatch):
    provider, store = FakeProvider(), FakeStore()
    monkeypatch.setattr("taxsentry.cockpit.JobStore", lambda: store)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda value: provider)
    monkeypatch.setattr("taxsentry.cockpit.describe_config", lambda value: "configured")
    cockpit = Cockpit(settings())
    async with cockpit.run_test(size=(80, 24)) as pilot:
        for command in ("/help", "/status", "/jobs", "/report", "/retry job", "/approve job", "/new", "/unknown"):
            await cockpit._command(command)
        await pilot.pause()
        assert len(cockpit.query(Markdown)) >= 9
    assert list(COMMANDS) == ["/help", "/status", "/gmail", "/jobs", "/report", "/retry", "/approve", "/new", "/exit"]
    assert store.requeued == [("job-123456", False), ("job-123456", True)]


@pytest.mark.asyncio
async def test_cockpit_reflows_and_streams_markdown(monkeypatch):
    monkeypatch.setattr("taxsentry.cockpit.JobStore", FakeStore)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda value: FakeProvider())
    cockpit = Cockpit(settings())
    async with cockpit.run_test(size=(120, 40)) as pilot:
        await cockpit._turn("hello")
        await pilot.resize_terminal(60, 20)
        await pilot.pause()
        assert cockpit.size.width == 60
        assert "TAXSENTRY" in str(cockpit.query_one("#topbar", Static).render())
        assert any("Xin chào" in str(widget.source) for widget in cockpit.query(Markdown))
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        assert "Gmail" in str(cockpit.query_one("#footer", Static).render())
        await cockpit._message("TaxSentry", "| A | B |\n|---|---|\n| tiếng Việt | `code` |\n\nhttps://example.com/" + "x" * 200, "assistant")
        await pilot.resize_terminal(50, 20)
        await pilot.pause()
        assert cockpit.query_one("#transcript").max_scroll_x == 0
        assert "60" in str(cockpit.query_one("#activity", Static).render())


@pytest.mark.asyncio
async def test_composer_submit_multiline_history_palette_and_latest(monkeypatch):
    monkeypatch.setattr("taxsentry.cockpit.JobStore", FakeStore)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda value: FakeProvider())
    cockpit = Cockpit(settings())
    submitted = []

    async def capture(value):
        submitted.append(value)

    cockpit._turn = capture
    async with cockpit.run_test(size=(80, 24)) as pilot:
        composer = cockpit.query_one(Composer)
        composer.focus()
        await pilot.press("h", "i", "shift+enter", "t", "h", "e", "r", "e")
        assert composer.text == "hi\nthere"
        await pilot.press("enter")
        await pilot.pause()
        assert submitted == ["hi\nthere"]
        cockpit.input_history[:] = ["first", "second"]
        cockpit.history_index = 2
        await pilot.press("up")
        assert composer.text.rstrip("\n") == "second"
        composer.text = "/gm"
        await pilot.pause()
        assert cockpit.query_one("#command-palette", Static).has_class("visible")
        await pilot.press("escape")
        assert not cockpit.query_one("#command-palette", Static).has_class("visible")
        cockpit.query_one("#new-content", Static).add_class("visible")
        await pilot.press("end")
        assert not cockpit.query_one("#new-content", Static).has_class("visible")


@pytest.mark.asyncio
async def test_tool_card_opens_full_overlay(monkeypatch):
    monkeypatch.setattr("taxsentry.cockpit.JobStore", FakeStore)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda value: FakeProvider())
    cockpit = Cockpit(settings())
    async with cockpit.run_test(size=(80, 24)) as pilot:
        card = ToolCard("lookup", "preview", "full output", True, 0.2)
        await cockpit.query_one("#transcript").mount(card)
        card.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(cockpit.screen, ToolOverlay)
        await pilot.press("escape")


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
    monkeypatch.setattr("taxsentry.cockpit.JobStore", FakeStore)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda value: provider)
    cockpit = Cockpit(settings())
    cockpit.exit = lambda *args, **kwargs: None
    await cockpit.action_exit_app()
    assert provider.closed


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
