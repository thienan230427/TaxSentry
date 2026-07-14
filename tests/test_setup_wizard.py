from __future__ import annotations

from copy import deepcopy

import pytest

from taxsentry.config import DEFAULT_SETTINGS
from taxsentry.setup_wizard import SetupSelection, _pick_model, authenticate_selection, run_setup_wizard


class FakeUI:
    def __init__(self, choices=(), texts=()):
        self.choices = list(choices)
        self.texts = list(texts)
        self.summaries = []

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


def config():
    return deepcopy(DEFAULT_SETTINGS)


def test_chat_profile_preserves_current_codex_credentials(monkeypatch):
    monkeypatch.setattr("taxsentry.setup_wizard._pick_model", lambda ui, settings, kind: ("", {"account": {"type": "chatgpt"}}))
    ui = FakeUI(choices=["chat", "codex", "existing", "save"])

    result = run_setup_wizard(config(), console=None, ui=ui)

    assert result and result.codex_auth == "existing"
    assert result.config["gmail"]["enabled"] is False
    assert result.config["telegram"]["enabled"] is False
    assert result.config["configured"] is True
    assert ui.summaries


def test_full_profile_collects_and_validates_every_enabled_service(monkeypatch, tmp_path):
    oauth = tmp_path / "credentials.json"
    oauth.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("taxsentry.setup_wizard._pick_model", lambda ui, settings, kind: ("local-model", {}))
    monkeypatch.setattr("taxsentry.setup_wizard.get_secret", lambda name: "")
    ui = FakeUI(
        choices=["full", "lmstudio", 60, "reauth", "replace", "save"],
        texts=[
            "http://127.0.0.1:1234/v1",
            "reports@example.com",
            str(oauth),
            "accounting@example.com, tax@example.com",
            "director@example.com",
            "123,-456",
            "telegram-token",
        ],
    )

    result = run_setup_wizard(config(), console=None, ui=ui)

    assert result and result.gmail_auth == "reauth" and result.telegram_auth == "replace"
    assert result.telegram_token == "telegram-token"
    assert result.config["gmail"]["trusted_senders"] == ["accounting@example.com", "tax@example.com"]
    assert result.config["director"]["telegram_chat_ids"] == ["123", "-456"]
    assert result.config["worker"]["poll_seconds"] == 60


def test_summary_cancel_returns_without_selection(monkeypatch):
    monkeypatch.setattr("taxsentry.setup_wizard._pick_model", lambda ui, settings, kind: ("", {}))
    ui = FakeUI(choices=["chat", "lmstudio", "cancel"], texts=["http://127.0.0.1:1234/v1"])
    assert run_setup_wizard(config(), console=None, ui=ui) is None


def test_model_picker_uses_discovered_model_and_retries(monkeypatch):
    calls = []

    async def catalog():
        calls.append(1)
        return ({}, [], "offline") if len(calls) == 1 else ({}, [("gpt-tax", "GPT Tax")], "")

    monkeypatch.setattr("taxsentry.setup_wizard._codex_catalog", catalog)
    ui = FakeUI(choices=["__retry__", "gpt-tax"])
    model, _ = _pick_model(ui, config(), "codex")
    assert model == "gpt-tax" and len(calls) == 2


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

