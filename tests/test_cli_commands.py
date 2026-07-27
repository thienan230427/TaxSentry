import json
from types import SimpleNamespace

import pytest

from taxsentry.data_plane.migration import MigrationFailure, MigrationReport
from taxsentry.tui import _parser, doctor, main


@pytest.mark.parametrize(("arguments", "command"), [(["setup"], "setup"), (["status"], "status"), (["doctor", "--fix"], "doctor"), (["update"], "update"), (["update", "--main"], "update"), (["migrate-v3"], "migrate-v3")])
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


@pytest.mark.parametrize(("conflicts", "exit_code"), [(0, 0), (2, 1)])
def test_migrate_v3_backs_up_before_schema_and_writes_report(
    monkeypatch, tmp_path, conflicts, exit_code
):
    source = tmp_path / "legacy.db"
    source.write_bytes(b"legacy")
    backup = tmp_path / "backup"
    settings = {"configured": True, "agent": {"company_id": "company-a"}}
    calls = []
    queue = SimpleNamespace(ensure_schema=lambda: calls.append("schema"))
    object_store = object()
    report = SimpleNamespace(imported=7, skipped=1, conflicts=conflicts)

    monkeypatch.setattr("taxsentry.tui.load_config", lambda: settings)
    monkeypatch.setattr(
        "taxsentry.tui.job_queue_from_settings",
        lambda value: calls.append(("queue", value)) or queue,
    )

    def export(value, destination):
        calls.append(("backup", value, destination))
        destination.mkdir(exist_ok=True)
        (destination / "snapshot.db").write_bytes(b"snapshot")
        return destination / "manifest.json"

    monkeypatch.setattr("taxsentry.tui.export_sqlite_snapshot", export)
    monkeypatch.setattr(
        "taxsentry.tui.object_store_from_settings",
        lambda value: calls.append(("objects", value)) or object_store,
    )
    monkeypatch.setattr(
        "taxsentry.tui.migrate_sqlite_database",
        lambda *args, **kwargs: calls.append(("migrate", args, kwargs)) or report,
    )
    monkeypatch.setattr(
        "taxsentry.tui.write_migration_report",
        lambda value, destination: calls.append(("report", value, destination)),
    )

    assert (
        main(
            [
                "migrate-v3",
                "--sqlite",
                str(source),
                "--backup-dir",
                str(backup),
                "--company-id",
                "company-b",
            ]
        )
        == exit_code
    )
    assert calls[0][0] == "queue"
    assert calls[1] == ("backup", source.resolve(), backup.resolve())
    assert calls[2] == "schema"
    assert calls[3][0] == "objects"
    assert calls[4][1][0] == backup / "snapshot.db"
    assert calls[4][2]["company_id"] == "company-b"
    assert calls[4][2]["legacy_source_root"] == source.parent
    assert calls[4][2]["approved_legacy_roots"] == (
        source.parent / "downloads",
        source.parent / "outputs",
    )
    assert calls[5] == ("report", report, backup / "migration-report.json")
    assert source.read_bytes() == b"legacy"


def test_migrate_v3_reports_missing_postgres_configuration_before_backup(
    monkeypatch, tmp_path, capsys
):
    source = tmp_path / "legacy.db"
    source.write_bytes(b"legacy")
    backup = tmp_path / "backup"
    monkeypatch.setattr("taxsentry.tui.load_config", lambda: {"configured": True})
    monkeypatch.setattr(
        "taxsentry.tui.job_queue_from_settings",
        lambda _settings: (_ for _ in ()).throw(
            ValueError("Configure data_plane.postgres_dsn or TAXSENTRY_POSTGRES_DSN")
        ),
    )
    monkeypatch.setattr(
        "taxsentry.tui.export_sqlite_snapshot",
        lambda *_args: pytest.fail("backup must not start without a PostgreSQL target"),
    )

    assert (
        main(
            [
                "migrate-v3",
                "--sqlite",
                str(source),
                "--backup-dir",
                str(backup),
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    report = json.loads((backup / "migration-report.json").read_text(encoding="utf-8"))
    assert "ValueError" in output
    assert "TAXSENTRY_POSTGRES_DSN" not in output
    assert report["status"] == "failed"
    assert report["stage"] == "configuration"
    assert report["error_type"] == "ValueError"
    assert "postgresql://" not in json.dumps(report)


def test_migrate_v3_writes_sanitized_partial_report(monkeypatch, tmp_path, capsys):
    source = tmp_path / "legacy.db"
    source.write_bytes(b"legacy")
    backup = tmp_path / "backup"
    queue = SimpleNamespace(ensure_schema=lambda: None)
    partial = MigrationReport(
        imported=2,
        status="partial",
        stage="import",
        error_type="OperationalError",
    )

    monkeypatch.setattr("taxsentry.tui.load_config", lambda: {"configured": True})
    monkeypatch.setattr("taxsentry.tui.job_queue_from_settings", lambda _settings: queue)

    def export(_source, destination):
        (destination / "snapshot.db").write_bytes(b"snapshot")
        return destination / "manifest.json"

    monkeypatch.setattr("taxsentry.tui.export_sqlite_snapshot", export)
    monkeypatch.setattr("taxsentry.tui.object_store_from_settings", lambda _settings: object())
    monkeypatch.setattr(
        "taxsentry.tui.migrate_sqlite_database",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(MigrationFailure(partial)),
    )

    assert (
        main(
            [
                "migrate-v3",
                "--sqlite",
                str(source),
                "--backup-dir",
                str(backup),
            ]
        )
        == 2
    )
    saved = json.loads((backup / "migration-report.json").read_text(encoding="utf-8"))
    assert saved["status"] == "partial" and saved["imported"] == 2
    assert "OperationalError" in capsys.readouterr().out
    assert "password" not in json.dumps(saved).casefold()


def test_bare_command_opens_cockpit(monkeypatch):
    calls = []

    class App:
        def __init__(self, settings):
            calls.append(settings)

        def run(self):
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

        def run(self):
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
