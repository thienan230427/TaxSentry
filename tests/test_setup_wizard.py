from __future__ import annotations

import asyncio
from copy import deepcopy
from io import StringIO

import pytest
from rich.console import Console
from textual.widgets import Input, Select

from taxsentry.config import DEFAULT_SETTINGS
from taxsentry.setup_wizard import (
    Cancelled,
    SetupSelection,
    SetupWizardApp,
    WizardUI,
    _codex_session,
    _collect,
    _pick_model,
    authenticate_selection,
    run_setup_wizard,
)


class FakeUI:
    def __init__(self, choices=(), texts=()):
        self.choices = list(choices)
        self.texts = list(texts)
        self.summaries = []
        self.output = StringIO()
        self.console = Console(file=self.output, force_terminal=False)

    def choose(self, *args, **kwargs):
        return self.choices.pop(0)

    def text(self, *args, validate=None, **kwargs):
        value = self.texts.pop(0)
        assert not validate or validate(value)
        return value

    def message(self, *args, **kwargs):
        pass

    def summary(self, rows):
        self.summaries.append(rows)

    async def wait(self, awaitable, timeout=300):
        return await awaitable


def config():
    return deepcopy(DEFAULT_SETTINGS)


@pytest.mark.asyncio
async def test_textual_wizard_language_step_and_back_navigation():
    app = SetupWizardApp(config())
    async with app.run_test(size=(60, 20)) as pilot:
        app.query_one("#language", Select).value = "en"
        await pilot.click("#next")
        await pilot.pause()
        assert app.candidate["ui"]["language"] == "en" and app.step == 1
        await pilot.click("#back")
        await pilot.pause()
        assert app.step == 0 and app.size.width == 60


@pytest.mark.asyncio
async def test_textual_wizard_masks_secrets_and_never_summarizes_them():
    app = SetupWizardApp(config())
    async with app.run_test(size=(80, 24)) as pilot:
        app.step = 4
        await app._render_step()
        password = app.query_one("#gmail-password", Input)
        password.value = "super-secret"
        assert password.password is True
        app.step = 5
        await app._render_step()
        await pilot.pause()
        assert "super-secret" not in str(app.query_one("#summary").render())


def test_wait_uses_timeout_and_propagates_cancel():
    ui = WizardUI(Console(file=StringIO()))
    with pytest.raises(TimeoutError):
        asyncio.run(ui.wait(asyncio.sleep(1), timeout=0.001))


def test_unicode_symbols_fall_back_for_ascii_terminal(monkeypatch):
    monkeypatch.setattr("taxsentry.setup_wizard.sys.stdout", type("AsciiOutput", (), {"encoding": "ascii"})())
    assert WizardUI._supports_unicode() is False


def test_chat_profile_preserves_current_codex_credentials(monkeypatch):
    async def session(ui):
        return {"account": {"type": "chatgpt"}}, []

    monkeypatch.setattr("taxsentry.setup_wizard._codex_session", session)
    ui = FakeUI(choices=["chat", "codex", "", "save"])

    result = run_setup_wizard(config(), console=None, ui=ui)

    assert result and result.codex_auth == "existing"
    assert result.config["gmail"]["enabled"] is False
    assert result.config["telegram"]["enabled"] is False
    assert result.config["configured"] is True
    assert ui.summaries


def test_full_profile_collects_and_validates_every_enabled_service(monkeypatch):
    monkeypatch.setattr("taxsentry.setup_wizard._pick_model", lambda ui, settings, kind: ("local-model", {}))
    monkeypatch.setattr("taxsentry.setup_wizard.get_secret", lambda name: "")
    ui = FakeUI(
        choices=["full", "lmstudio", 60, "replace", "save"],
        texts=[
            "http://127.0.0.1:1234/v1",
            "reports@example.com",
            "abcd efgh ijkl mnop",
            "123,-456",
            "telegram-token",
        ],
    )

    result = run_setup_wizard(config(), console=None, ui=ui)

    assert result and result.gmail_auth == "replace" and result.telegram_auth == "replace"
    assert result.gmail_password == "abcd efgh ijkl mnop"
    assert "gmail_password" not in result.config["gmail"]
    assert result.telegram_token == "telegram-token"
    assert "trusted_senders" not in result.config["gmail"]
    assert "email" not in result.config["director"]
    assert result.gmail_reset_uid
    assert result.config["director"]["telegram_chat_ids"] == ["123", "-456"]
    assert result.config["worker"]["poll_seconds"] == 60


def test_reenabling_same_gmail_resets_worker_uid(monkeypatch):
    settings = config()
    settings["gmail"].update({"enabled": False, "account": "boss@example.com", "process_after_uid": 99})
    monkeypatch.setattr("taxsentry.setup_wizard._pick_model", lambda ui, value, kind: ("local", {}))
    monkeypatch.setattr("taxsentry.setup_wizard.get_secret", lambda name: "")
    ui = FakeUI(choices=["email", "lmstudio", 60], texts=["http://127.0.0.1:1234/v1", "boss@example.com", "abcd efgh ijkl mnop"])
    assert _collect(settings, ui).gmail_reset_uid


def test_summary_cancel_returns_without_selection(monkeypatch):
    monkeypatch.setattr("taxsentry.setup_wizard._pick_model", lambda ui, settings, kind: ("", {}))
    ui = FakeUI(choices=["chat", "lmstudio", "cancel"], texts=["http://127.0.0.1:1234/v1"])
    assert run_setup_wizard(config(), console=None, ui=ui) is None


def test_model_picker_uses_only_discovered_codex_models():
    ui = FakeUI(choices=["gpt-tax"])
    model, _ = _pick_model(ui, config(), "codex", [("gpt-tax", "GPT Tax", ("medium", "high"))])
    assert model == "gpt-tax"


def test_codex_oauth_completes_before_model_list(monkeypatch):
    events = []

    class Client:
        async def account(self, refresh=False):
            events.append("account-refresh" if refresh else "account")
            return {"account": {"type": "chatgpt", "email": "boss@example.com"}} if refresh else {"account": None, "requiresOpenaiAuth": True}

        async def start_login(self, device_code=False):
            events.append("login-start")
            return {"loginId": "login-1", "authUrl": "https://chatgpt.com/oauth"}

        async def wait_login(self, login_id):
            events.append(f"login-completed:{login_id}")

        async def cancel_login(self, login_id):
            events.append(f"cancel:{login_id}")

        async def models(self):
            events.append("models")
            return [("gpt-tax", "GPT Tax", ())]

        async def close(self):
            events.append("close")

    monkeypatch.setattr("taxsentry.setup_wizard.CodexAppServerProvider", Client)
    monkeypatch.setattr("taxsentry.setup_wizard.webbrowser.open", lambda url: False)
    account, models = asyncio.run(_codex_session(FakeUI(choices=["browser"])))
    assert account["account"]["email"] == "boss@example.com"
    assert models[0][0] == "gpt-tax"
    assert events.index("login-completed:login-1") < events.index("models")


def test_codex_choices_do_not_nest_the_oauth_event_loop(monkeypatch):
    class Client:
        async def account(self, refresh=False):
            return {"account": {"type": "chatgpt"}}

        async def models(self):
            return []

        async def close(self):
            pass

    class LoopCheckingUI(FakeUI):
        def choose(self, *args, **kwargs):
            asyncio.run(asyncio.sleep(0))
            return "existing"

    monkeypatch.setattr("taxsentry.setup_wizard.CodexAppServerProvider", Client)
    account, models = asyncio.run(_codex_session(LoopCheckingUI()))
    assert account["account"]["type"] == "chatgpt" and models == []


def test_codex_oauth_cancel_sends_login_cancel(monkeypatch):
    cancelled = []

    class Client:
        async def wait_login(self, login_id):
            await asyncio.sleep(10)

        async def cancel_login(self, login_id):
            cancelled.append(login_id)

    class CancelUI(FakeUI):
        async def wait(self, awaitable, timeout=300):
            awaitable.close()
            raise Cancelled

    from taxsentry.setup_wizard import _await_login

    with pytest.raises(Cancelled):
        asyncio.run(_await_login(CancelUI(), Client(), {"loginId": "login-9"}))
    assert cancelled == ["login-9"]


def test_failed_telegram_validation_never_replaces_secret(monkeypatch):
    settings = config()
    settings["gmail"]["enabled"] = False
    settings["telegram"]["enabled"] = True
    selection = SetupSelection(settings, telegram_auth="replace", telegram_token="invalid")
    stored = []
    monkeypatch.setattr("taxsentry.setup_wizard.lmstudio_models", lambda spec: ["model"])

    async def fail(token):
        raise RuntimeError("invalid token")

    monkeypatch.setattr("taxsentry.setup_wizard._telegram_auth", fail)
    monkeypatch.setattr("taxsentry.setup_wizard.set_secret", lambda *args: stored.append(args))

    class Console:
        def print(self, *args, **kwargs):
            pass

    assert authenticate_selection(selection, Console()) == 1
    assert stored == []


def test_successful_gmail_setup_records_current_uid(monkeypatch):
    settings = config()
    settings["gmail"].update({"enabled": True, "account": "boss@gmail.com", "process_after_uid": None})
    settings["telegram"]["enabled"] = False
    selection = SetupSelection(settings, gmail_password="abcd efgh ijkl mnop", gmail_reset_uid=True)
    saved = []

    class Gmail:
        def __init__(self, value): pass
        def authenticate(self, **kwargs): pass
        def latest_uid(self): return 42

    monkeypatch.setattr("taxsentry.setup_wizard.GmailClient", Gmail)
    monkeypatch.setattr("taxsentry.setup_wizard.lmstudio_models", lambda spec: ["model"])
    monkeypatch.setattr("taxsentry.setup_wizard.set_secret", lambda *args: None)
    monkeypatch.setattr("taxsentry.setup_wizard.save_config", lambda value: saved.append(value))

    assert authenticate_selection(selection, Console(file=StringIO())) == 0
    assert saved[0]["gmail"]["process_after_uid"] == 42


def test_setup_cancel_does_not_write_config(monkeypatch):
    from taxsentry import tui

    monkeypatch.setattr(tui, "load_config", config)
    monkeypatch.setattr(tui, "run_setup_wizard", lambda settings, console: None)
    monkeypatch.setattr(tui, "save_config", lambda settings: pytest.fail("config must not be written"))
    assert tui.setup() == 0
