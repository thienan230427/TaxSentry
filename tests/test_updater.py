from types import SimpleNamespace

import pytest

from taxsentry import updater


def result(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_git_clone_fast_forwards_and_syncs(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(updater, "_git_root", lambda: tmp_path)
    monkeypatch.setattr(updater.shutil, "which", lambda name: name)

    def run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["status", "--porcelain"]:
            return result(stdout="")
        if command[1] == "rev-parse":
            return result(stdout="origin/main\n")
        return result()

    monkeypatch.setattr(updater, "_run", run)
    code, _ = updater.perform_update()

    assert code == 0
    assert ["git", "pull", "--ff-only"] in calls
    assert ["uv", "sync", "--locked"] in calls


def test_git_clone_refuses_dirty_tree(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(updater, "_git_root", lambda: tmp_path)
    monkeypatch.setattr(updater.shutil, "which", lambda name: name)
    monkeypatch.setattr(updater, "_run", lambda command, **kwargs: calls.append(command) or result(stdout=" M README.md\n"))

    code, message = updater.perform_update()

    assert code == 1
    assert "commit" in message
    assert not any("pull" in command for command in calls)


def test_git_main_requires_main_branch(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "_git_root", lambda: tmp_path)
    monkeypatch.setattr(updater.shutil, "which", lambda name: name)

    def run(command, **kwargs):
        return result(stdout="feature/test\n") if command[1:3] == ["branch", "--show-current"] else result()

    monkeypatch.setattr(updater, "_run", run)
    code, message = updater.perform_update(main=True)
    assert code == 1
    assert "nhánh `main`" in message


@pytest.mark.parametrize(
    ("latest", "expected_install"),
    [("1.1.7", False), ("2.1.0", True)],
)
def test_npm_stable_never_downgrades(monkeypatch, latest, expected_install):
    calls = []
    monkeypatch.setattr(updater, "_git_root", lambda: None)
    monkeypatch.setattr(updater, "_npm_runtime", lambda: True)
    monkeypatch.setattr(updater.shutil, "which", lambda name: f"{name}.CMD")

    def run(command, **kwargs):
        calls.append(command)
        return result(stdout=f'"{latest}"\n')

    monkeypatch.setattr(updater, "_run", run)
    code, _ = updater.perform_update()

    assert code == 0
    assert any(command[1:4] == ["install", "-g", "taxsentry@latest"] for command in calls) is expected_install


def test_npm_main_updates_the_managed_python(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "_git_root", lambda: None)
    monkeypatch.setattr(updater, "_npm_runtime", lambda: True)
    monkeypatch.setattr(updater.shutil, "which", lambda name: "uv.exe" if name == "uv" else None)
    monkeypatch.setattr(updater, "_run", lambda command, **kwargs: calls.append(command) or result())

    code, _ = updater.perform_update(main=True)

    assert code == 0
    assert calls == [[
        "uv.exe",
        "pip",
        "install",
        "--python",
        str(updater.PYTHON),
        "--upgrade",
        "--reinstall-package",
        updater.PACKAGE,
        updater.MAIN_SOURCE,
    ]]


@pytest.mark.parametrize(
    ("main", "expected"),
    [
        (False, ["uv", "tool", "upgrade", updater.PACKAGE]),
        (True, ["uv", "tool", "install", "--force", updater.MAIN_SOURCE]),
    ],
)
def test_uv_tool_uses_the_selected_channel(monkeypatch, main, expected):
    calls = []
    monkeypatch.setattr(updater, "_git_root", lambda: None)
    monkeypatch.setattr(updater, "_npm_runtime", lambda: False)
    monkeypatch.setattr(updater.shutil, "which", lambda name: name)
    monkeypatch.setattr(updater, "_run", lambda command, **kwargs: calls.append(command) or result())

    assert updater.perform_update(main=main)[0] == 0
    assert calls == [expected]


def test_failed_update_does_not_touch_user_data(monkeypatch, tmp_path):
    marker = tmp_path / "taxsentry.db"
    marker.write_text("important", encoding="utf-8")
    monkeypatch.setattr(updater, "_git_root", lambda: None)
    monkeypatch.setattr(updater, "_npm_runtime", lambda: False)
    monkeypatch.setattr(updater.shutil, "which", lambda name: name)
    monkeypatch.setattr(updater, "_run", lambda command, **kwargs: result(returncode=7))

    assert updater.perform_update()[0] == 7
    assert marker.read_text(encoding="utf-8") == "important"


def test_missing_tool_and_os_error_are_reported(monkeypatch):
    monkeypatch.setattr(updater, "_git_root", lambda: None)
    monkeypatch.setattr(updater, "_npm_runtime", lambda: False)
    monkeypatch.setattr(updater.shutil, "which", lambda name: None)
    assert updater.perform_update()[0] == 1

    monkeypatch.setattr(updater.shutil, "which", lambda name: name)
    monkeypatch.setattr(updater, "_run", lambda command, **kwargs: (_ for _ in ()).throw(OSError("blocked")))
    code, message = updater.perform_update()
    assert code == 1
    assert "blocked" in message
