import pytest

from taxsentry.tui import _parser, doctor, main


@pytest.mark.parametrize(("arguments", "command"), [(["setup"], "setup"), (["status"], "status"), (["doctor", "--fix"], "doctor"), (["update"], "update"), (["update", "--main"], "update")])
def test_only_terminal_runtime_commands_are_public(arguments, command):
    assert _parser().parse_args(arguments).command == command


@pytest.mark.parametrize("command", ["start", "dashboard", "chat", "gateway", "worker", "jobs", "report", "auth", "service"])
def test_removed_commands_are_rejected(command):
    with pytest.raises(SystemExit):
        _parser().parse_args([command])


def test_update_flag_is_dispatched(monkeypatch):
    calls = []
    monkeypatch.setattr("taxsentry.tui.perform_update", lambda **kwargs: calls.append(kwargs) or (0, "ok"))
    assert main(["update", "--main"]) == 0
    assert calls == [{"main": True}]


def test_bare_command_opens_cockpit(monkeypatch):
    calls = []

    class App:
        def __init__(self, settings):
            calls.append(settings)

        async def run(self):
            return 0

    settings = {"configured": True}
    monkeypatch.setattr("taxsentry.tui.load_config", lambda: settings)
    monkeypatch.setattr("taxsentry.tui.Cockpit", App)
    assert main([]) == 0 and calls == [settings]


def test_bare_command_runs_setup_when_unconfigured(monkeypatch):
    states = iter([{"configured": False}, {"configured": True}])
    calls = []

    class App:
        def __init__(self, settings):
            calls.append(settings)

        async def run(self):
            return 0

    monkeypatch.setattr("taxsentry.tui.load_config", lambda: next(states))
    monkeypatch.setattr("taxsentry.tui.setup", lambda: calls.append("setup") or 0)
    monkeypatch.setattr("taxsentry.tui.Cockpit", App)
    assert main([]) == 0
    assert calls[0] == "setup" and calls[1]["configured"] is True


def test_doctor_skips_gmail_and_ocr_for_chat_profile(monkeypatch, tmp_path):
    settings = {
        "provider": {"kind": "lmstudio", "model": "", "base_url": "http://localhost"},
        "gmail": {"enabled": False}, "telegram": {"enabled": False}, "ocr": {"languages": ["vie", "eng"]}, "director": {},
    }
    monkeypatch.setattr("taxsentry.tui.load_config", lambda: settings)
    monkeypatch.setattr("taxsentry.tui.APP_HOME", tmp_path)
    monkeypatch.setattr("taxsentry.tui.health_check", lambda spec: (True, "ok"))
    monkeypatch.setattr("taxsentry.tui.get_secret", lambda name: pytest.fail("disabled integrations must not read secrets"))
    assert doctor() == 0
