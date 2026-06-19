"""Cross-platform runtime helpers for TaxSentry."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT_MARKERS = ("pyproject.toml", "requirements.txt")


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
    if in_virtualenv():
        return

    venv_python = get_venv_python()
    if not venv_python:
        print("⚠️ Cảnh báo: Không tìm thấy môi trường ảo .venv cục bộ. Hệ thống sẽ cố gắng chạy bằng Python hệ thống.")
        return

    args = [str(venv_python)] + (argv or sys.argv)
    try:
        raise SystemExit(subprocess.run(args).returncode)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Không thể tự động chuyển hướng sang môi trường ảo: {exc}")
        print("Vui lòng kích hoạt thủ công .venv và chạy lại.")
        raise SystemExit(1)
