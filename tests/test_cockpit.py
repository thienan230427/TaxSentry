from __future__ import annotations

from types import SimpleNamespace

import pytest

from taxsentry.bot import telegram_bot
from taxsentry.cockpit import SYSTEM, Cockpit


class FakeProvider:
    def __init__(self):
        self.closed = False

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


class FakePrompt:
    def __init__(self, **kwargs):
        pass


@pytest.mark.asyncio
async def test_cockpit_switches_provider_and_closes_previous(monkeypatch):
    old, new = FakeProvider(), FakeProvider()
    monkeypatch.setattr("taxsentry.cockpit.JobStore", FakeStore)
    monkeypatch.setattr("taxsentry.cockpit.PromptSession", FakePrompt)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda settings: new if settings["provider"]["kind"] == "codex" else old)
    monkeypatch.setattr("taxsentry.cockpit.save_config", lambda settings: None)
    cockpit = Cockpit({"configured": True, "provider": {"kind": "lmstudio", "model": ""}})

    await cockpit._command("/provider codex")

    assert old.closed
    assert cockpit.provider is new


@pytest.mark.asyncio
async def test_cockpit_approve_and_clear(monkeypatch):
    provider, store = FakeProvider(), FakeStore()
    monkeypatch.setattr("taxsentry.cockpit.JobStore", lambda: store)
    monkeypatch.setattr("taxsentry.cockpit.PromptSession", FakePrompt)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda settings: provider)
    cockpit = Cockpit({"configured": True, "provider": {"kind": "lmstudio", "model": ""}})
    cockpit.history.append({"role": "user", "content": "test"})

    await cockpit._command("/approve job-123")
    await cockpit._command("/clear")

    assert store.requeued == [("job-123456", True)]
    assert cockpit.history == [{"role": "system", "content": SYSTEM}]


@pytest.mark.asyncio
async def test_cockpit_command_surface_and_invalid_states(monkeypatch):
    provider, store, output = FakeProvider(), FakeStore(), []
    monkeypatch.setattr("taxsentry.cockpit.JobStore", lambda: store)
    monkeypatch.setattr("taxsentry.cockpit.PromptSession", FakePrompt)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda settings: provider)
    monkeypatch.setattr("taxsentry.cockpit.describe_config", lambda settings: "configured")
    cockpit = Cockpit({"configured": True, "provider": {"kind": "lmstudio", "model": ""}})
    cockpit.console = SimpleNamespace(print=lambda *args, **kwargs: output.append(args[0] if args else ""))

    for command in ("/help", "/status", "/auth", "/jobs", "/latest", "/report", "/provider invalid", "/retry job-123", "/unknown"):
        await cockpit._command(command)

    assert store.requeued == [("job-123456", False)]
    assert "configured" in output
    assert "Doanh thu ổn định" in output
    assert any("Lệnh chưa hỗ trợ" in str(item) for item in output)

    store.job["state"] = "completed"
    await cockpit._command("/retry job-123")
    assert any("Không tìm thấy job" in str(item) for item in output)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["/exit", "/quit"])
async def test_cockpit_exit_aliases_close_provider(monkeypatch, command):
    provider = FakeProvider()

    class ExitPrompt:
        async def prompt_async(self, *args, **kwargs):
            return command

    monkeypatch.setattr("taxsentry.cockpit.JobStore", FakeStore)
    monkeypatch.setattr("taxsentry.cockpit.PromptSession", lambda **kwargs: ExitPrompt())
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda settings: provider)
    cockpit = Cockpit({"configured": True, "provider": {"kind": "lmstudio", "model": ""}})

    assert await cockpit.run() == 0
    assert provider.closed


@pytest.mark.asyncio
async def test_telegram_commands_are_registered_and_authorized(monkeypatch):
    import telegram.ext

    replies, handlers = [], []

    class App:
        def add_handler(self, handler):
            handlers.append(handler)

    class Builder:
        def token(self, token):
            return self

        def build(self):
            return App()

    class Application:
        @staticmethod
        def builder():
            return Builder()

    store = FakeStore()
    monkeypatch.setattr(telegram.ext, "Application", Application)
    monkeypatch.setattr(telegram.ext, "CommandHandler", lambda name, callback: (name, callback))
    monkeypatch.setattr(telegram.ext, "MessageHandler", lambda filters, callback: ("chat", callback))
    monkeypatch.setattr(telegram_bot, "load_config", lambda: {"director": {"telegram_chat_ids": [42]}})
    monkeypatch.setattr(telegram_bot, "JobStore", lambda: store)
    monkeypatch.setattr(telegram_bot, "get_secret", lambda name: "token")

    telegram_bot.build_application()

    assert [handler[0] for handler in handlers[:-1]] == list(telegram_bot.COMMANDS)
    status = handlers[0][1]
    message = SimpleNamespace(reply_text=lambda text: replies.append(text))

    async def reply_text(text):
        replies.append(text)

    message.reply_text = reply_text
    await status(SimpleNamespace(effective_chat=SimpleNamespace(id=7), message=message), SimpleNamespace(args=[]))
    assert replies == []
    await status(SimpleNamespace(effective_chat=SimpleNamespace(id=42), message=message), SimpleNamespace(args=[]))
    assert replies and "Báo cáo" in replies[0]
