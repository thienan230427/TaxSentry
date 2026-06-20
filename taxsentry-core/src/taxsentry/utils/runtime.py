"""Cross-platform runtime helpers for TaxSentry."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT_MARKERS = ("pyproject.toml", "requirements.txt")


def _safe_console_print(message: str) -> None:
    """Print to console without crashing on limited encodings like cp1252."""
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return

    encoding = getattr(stream, "encoding", None) or "utf-8"
    text = f"{message}\n"
    try:
        stream.write(text)
    except UnicodeEncodeError:
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        if hasattr(stream, "buffer"):
            stream.buffer.write(safe_text.encode(encoding, errors="replace"))
        else:
            stream.write(safe_text)
    stream.flush()


def in_virtualenv() -> bool:
    return (sys.prefix != sys.base_prefix) or ("VIRTUAL_ENV" in os.environ)


def get_project_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__).resolve()).resolve()
    for candidate in [current, *current.parents]:
        if any((candidate / marker).exists() for marker in PROJECT_ROOT_MARKERS):
            return candidate
    return Path(__file__).resolve().parents[3]


def iter_venv_python_candidates(root_dir: Path | None = None) -> Iterable[Path]:
    root = (root_dir or get_project_root()).resolve()
    yield root / ".venv" / "Scripts" / "python.exe"
    yield root / ".venv" / "bin" / "python"


def get_venv_python(root_dir: Path | None = None) -> Path | None:
    for candidate in iter_venv_python_candidates(root_dir):
        if candidate.exists():
            return candidate
    return None


def bootstrap_into_venv(argv: list[str] | None = None) -> None:
    if os.getenv("TAXSENTRY_SKIP_BOOTSTRAP") == "1":
        return

    if in_virtualenv():
        return

    venv_python = get_venv_python()
    if not venv_python:
        _safe_console_print("⚠️ Cảnh báo: Không tìm thấy môi trường ảo .venv cục bộ. Hệ thống sẽ cố gắng chạy bằng Python hệ thống.")
        return

    current_executable = Path(sys.executable).resolve()
    if current_executable == venv_python.resolve():
        return

    args = [str(venv_python)] + (argv or sys.argv)
    env = os.environ.copy()
    env["TAXSENTRY_SKIP_BOOTSTRAP"] = "1"
    try:
        raise SystemExit(subprocess.run(args, env=env).returncode)
    except SystemExit:
        raise
    except Exception as exc:
        _safe_console_print(f"Không thể tự động chuyển hướng sang môi trường ảo: {exc}")
        _safe_console_print("Vui lòng kích hoạt thủ công .venv và chạy lại.")
        raise SystemExit(1)
