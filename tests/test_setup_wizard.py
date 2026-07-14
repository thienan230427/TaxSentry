from __future__ import annotations

import asyncio
from copy import deepcopy
from io import StringIO

import pytest
from rich.console import Console

from taxsentry.config import DEFAULT_SETTINGS
from taxsentry.setup_wizard import (
    Cancelled,
    SetupSelection,
    WizardUI,
    _codex_session,
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


def inline_ui():
    output = StringIO()
    ui = WizardUI.__new__(WizardUI)
    ui.console = Console(file=output, force_terminal=False, width=50)
    ui.unicode = True
    ui.marker, ui.done, ui.line = "◆", "✓", "│"
    return ui, output


def test_inline_menu_is_transient_and_supports_keyboard_cancel(monkeypatch):
    ui, output = inline_ui()
    captured = {}
    radio_options = {}
    from prompt_toolkit.widgets import RadioList

    def radio(*args, **kwargs):
        radio_options.update(kwargs)
        return RadioList(*args, **kwargs)

    class InlineApplication:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            return "chat"

    monkeypatch.setattr("taxsentry.setup_wizard.Application", InlineApplication)
    monkeypatch.setattr("taxsentry.setup_wizard.RadioList", radio)
    assert ui.choose("Hồ sơ / Profile", "Chọn hồ sơ / Choose a profile", [("chat", "Chat Only\nTerminal cockpit")], "chat") == "chat"

    keys = {getattr(key, "value", key) for binding in captured["key_bindings"].bindings for key in binding.keys}
    assert captured["full_screen"] is False and captured["erase_when_done"] is True
    assert {"c-m", "escape", "c-c"} <= keys
    assert radio_options["show_numbers"] is True
    assert "✓ Hồ sơ  Chat Only" in output.getvalue()


def test_password_input_is_erased_and_never_echoed(monkeypatch):
    ui, output = inline_ui()
    options = {}

    class Session:
        def __init__(self, *args, **kwargs):
            options.update(kwargs)

        def prompt(self, **kwargs):
            return "super-secret"

    monkeypatch.setattr("taxsentry.setup_wizard.PromptSession", Session)
    assert ui.text("Telegram", "Bot token", password=True) == "super-secret"
    assert options["is_password"] is True and options["erase_when_done"] is True
    assert "super-secret" not in output.getvalue() and "••••••" in output.getvalue()


def test_login_wait_supports_escape_and_ctrl_c(monkeypatch):
    ui, _ = inline_ui()
    captured = {}

    class WaitApplication:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run_async(self):
            return False

    monkeypatch.setattr("taxsentry.setup_wizard.Application", WaitApplication)
    with pytest.raises(Cancelled):
        asyncio.run(ui.wait(asyncio.sleep(10)))
    keys = {getattr(key, "value", key) for binding in captured["key_bindings"].bindings for key in binding.keys}
    assert {"escape", "c-c"} <= keys


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
            "accounting@example.com, tax@example.com",
            "director@example.com",
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
    assert result.config["gmail"]["trusted_senders"] == ["accounting@example.com", "tax@example.com"]
    assert result.config["director"]["telegram_chat_ids"] == ["123", "-456"]
    assert result.config["worker"]["poll_seconds"] == 60


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


def test_setup_cancel_does_not_write_config(monkeypatch):
    from taxsentry import tui

    monkeypatch.setattr(tui, "load_config", config)
    monkeypatch.setattr(tui, "run_setup_wizard", lambda settings, console: None)
    monkeypatch.setattr(tui, "save_config", lambda settings: pytest.fail("config must not be written"))
    assert tui.setup() == 0
