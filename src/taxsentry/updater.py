from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import APP_HOME

PACKAGE = "taxsentry-agent"
MAIN_SOURCE = "git+https://github.com/thienan230427/TaxSentry.git@main"
PACKAGE_FILE = Path(__file__).resolve()
PYTHON = Path(sys.executable).resolve()
SERVICE_HINT = "Nếu service đang chạy: `taxsentry service stop` rồi `taxsentry service start`."


def _run(command: list[str], *, cwd: Path | None = None, capture: bool = False):
    return subprocess.run(command, cwd=cwd, check=False, text=True, capture_output=capture)


def _git_root() -> Path | None:
    for parent in PACKAGE_FILE.parents:
        if (parent / ".git").exists() and (parent / "pyproject.toml").exists():
            return parent
    return None


def _npm_runtime() -> bool:
    return PYTHON.is_relative_to((APP_HOME / "runtime" / "venv").resolve())


def _detail(result) -> str:
    return (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()


def _version(value: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", value.strip())
    return tuple(map(int, match.groups())) if match else None


def _git_update(root: Path, *, main: bool) -> tuple[int, str]:
    git, uv = shutil.which("git"), shutil.which("uv")
    if not git or not uv:
        return 1, "Cập nhật Git clone cần cả `git` và `uv` trong PATH."

    status = _run([git, "status", "--porcelain"], cwd=root, capture=True)
    if status.returncode:
        return status.returncode, f"Không kiểm tra được Git working tree: {_detail(status)}"
    if status.stdout.strip():
        return 1, "Working tree đang có thay đổi. Hãy commit hoặc tự stash trước khi cập nhật."

    if main:
        branch = _run([git, "branch", "--show-current"], cwd=root, capture=True)
        if branch.returncode or branch.stdout.strip() != "main":
            return 1, "`--main` chỉ fast-forward khi checkout đang ở nhánh `main`; không tự chuyển nhánh."
        pull = [git, "pull", "--ff-only", "origin", "main"]
    else:
        upstream = _run(
            [git, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd=root,
            capture=True,
        )
        if upstream.returncode:
            return 1, "Nhánh hiện tại chưa có upstream; hãy cấu hình upstream trước khi cập nhật."
        pull = [git, "pull", "--ff-only"]

    result = _run(pull, cwd=root)
    if result.returncode:
        return result.returncode, "Git pull thất bại; TaxSentry không reset hoặc ghi đè thay đổi local."
    synced = _run([uv, "sync", "--locked"], cwd=root)
    if synced.returncode:
        return synced.returncode, "Đã kéo code nhưng đồng bộ dependency thất bại; chạy lại `uv sync --locked`."
    return 0, f"TaxSentry đã fast-forward và đồng bộ dependency. {SERVICE_HINT}"


def _npm_update(*, main: bool) -> tuple[int, str]:
    if main:
        uv = shutil.which("uv")
        if not uv:
            return 1, "Không tìm thấy `uv`; không thể cài core từ nhánh main."
        result = _run([
            uv,
            "pip",
            "install",
            "--python",
            str(PYTHON),
            "--upgrade",
            "--reinstall-package",
            PACKAGE,
            MAIN_SOURCE,
        ])
        if result.returncode:
            return result.returncode, "Cập nhật core từ GitHub main thất bại; runtime hiện tại được giữ lại."
        return 0, f"TaxSentry core đã cập nhật từ GitHub main. {SERVICE_HINT}"

    npm = shutil.which("npm")
    if not npm:
        return 1, "Không tìm thấy `npm`; không thể cập nhật bản cài npm global."
    available = _run([npm, "view", "taxsentry", "version", "--json"], capture=True)
    if available.returncode:
        return available.returncode, f"Không kiểm tra được phiên bản npm: {_detail(available)}"
    try:
        latest = json.loads(available.stdout)
    except json.JSONDecodeError:
        latest = None
    current_version, latest_version = _version(__version__), _version(latest) if isinstance(latest, str) else None
    if not current_version or not latest_version:
        return 1, "Registry trả về phiên bản không hợp lệ; dừng để tránh downgrade."
    if latest_version <= current_version:
        return 0, f"Đang dùng {__version__}; npm stable {latest} không mới hơn nên không thay đổi."

    result = _run([npm, "install", "-g", "taxsentry@latest"])
    if result.returncode:
        return result.returncode, "npm update thất bại; bản đang cài được giữ lại."
    return 0, f"TaxSentry npm đã cập nhật lên {latest}; lần chạy sau sẽ nạp wheel mới. {SERVICE_HINT}"


def _uv_update(*, main: bool) -> tuple[int, str]:
    uv = shutil.which("uv")
    if not uv:
        return 1, "Không tìm thấy `uv`; cài uv rồi chạy lại."
    command = [uv, "tool", "install", "--force", MAIN_SOURCE] if main else [uv, "tool", "upgrade", PACKAGE]
    result = _run(command)
    if result.returncode:
        return result.returncode, "uv tool update thất bại; kiểm tra kết nối mạng và quyền ghi."
    channel = "GitHub main" if main else "kênh ổn định của uv tool"
    return 0, f"TaxSentry đã cập nhật từ {channel}. {SERVICE_HINT}"


def perform_update(*, main: bool = False) -> tuple[int, str]:
    try:
        root = _git_root()
        if root:
            return _git_update(root, main=main)
        if _npm_runtime():
            return _npm_update(main=main)
        return _uv_update(main=main)
    except OSError as exc:
        return 1, f"Không thể chạy trình cập nhật: {exc}"
