from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys

import keyring
from rich.console import Console
from rich.table import Table

from . import __version__
from .cockpit import Cockpit
from .config import APP_HOME, backup_v1_profile, describe_config, ensure_directories, load_config, save_config
from .providers import from_settings, health_check
from .secrets import get_secret
from .setup_wizard import authenticate_selection, run_setup_wizard
from .updater import perform_update

console = Console()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taxsentry", description="TaxSentry — Financial Sentinel TUI")
    parser.add_argument("--version", action="version", version=f"TaxSentry {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("setup", help="cấu hình provider, Gmail và Telegram")
    sub.add_parser("status", help="hiển thị cấu hình và trạng thái tích hợp")
    doctor_parser = sub.add_parser("doctor", help="kiểm tra các tích hợp")
    doctor_parser.add_argument("--fix", action="store_true")
    update_parser = sub.add_parser("update", help="cập nhật TaxSentry")
    update_parser.add_argument("--main", action="store_true", help="cập nhật core từ GitHub main")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "setup":
        return setup()
    if args.command == "status":
        console.print(describe_config(load_config()))
        return 0
    if args.command == "doctor":
        return doctor(fix=args.fix)
    if args.command == "update":
        return update(main=args.main)
    settings = load_config()
    if not settings.get("configured"):
        code = setup()
        settings = load_config()
        if code or not settings.get("configured"):
            return code
    return asyncio.run(Cockpit(settings).run())


def setup() -> int:
    config = load_config()
    try:
        selection = run_setup_wizard(config, console)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 2
    if selection is None:
        console.print("[yellow]Đã hủy; cấu hình không thay đổi / Cancelled; configuration unchanged.[/]")
        return 0
    backup = backup_v1_profile()
    if backup:
        console.print(f"[yellow]Đã backup profile v1 / Backed up v1 profile: {backup}[/]")
    return authenticate_selection(selection, console)


def doctor(*, fix: bool = False) -> int:
    settings, failed = load_config(), False
    if fix:
        ensure_directories()
        save_config(settings)
    checks = []
    ok, detail = health_check(from_settings(settings))
    checks.append(("Provider", ok, detail))
    gmail_required = bool(settings["gmail"].get("enabled", True))
    if gmail_required:
        tesseract = shutil.which("tesseract")
        required_languages = set(settings["ocr"].get("languages", ["vie", "eng"]))
        ocr_languages = _ocr_languages(tesseract) if tesseract else set()
        if fix and (not tesseract or not required_languages <= ocr_languages):
            _install_tesseract()
            tesseract = shutil.which("tesseract")
            ocr_languages = _ocr_languages(tesseract) if tesseract else set()
        missing = sorted(required_languages - ocr_languages)
        checks.append(("Tesseract", bool(tesseract) and not missing, tesseract if not missing else f"Thiếu {missing}; {_tesseract_hint()}"))
        gmail_account = settings["gmail"].get("account") or "default"
        try:
            gmail_token = get_secret(f"gmail-app-password:{gmail_account}")
        except keyring.errors.KeyringError:
            gmail_token = ""
        checks.append(("Gmail App Password", bool(gmail_token), "stored in keyring" if gmail_token else "run `taxsentry setup`"))
        marker = settings["gmail"].get("process_after_uid")
        checks.append(("Gmail sender policy", True, "all senders; automatic processing only after setup marker"))
        checks.append(("Gmail worker marker", marker is not None, str(marker) if marker is not None else "run `taxsentry setup`"))
        libreoffice = shutil.which("soffice")
        checks.append(("LibreOffice", True, libreoffice or "optional; required only for .doc/.xls/.ppt"))
    else:
        checks.append(("Gmail + OCR", True, "SKIP — disabled by setup profile"))
    telegram_required = bool(settings.get("telegram", {}).get("enabled"))
    try:
        telegram_token = get_secret("telegram:bot-token") if telegram_required else "disabled"
    except keyring.errors.KeyringError:
        telegram_token = ""
    checks.append(("Telegram", not telegram_required or bool(telegram_token), "configured" if telegram_token and telegram_required else str(telegram_token)))
    checks.append(("Data directory", APP_HOME.is_dir() and os.access(APP_HOME, os.W_OK), str(APP_HOME)))
    table = Table("Check", "Status", "Detail")
    for name, good, message in checks:
        table.add_row(name, "OK" if good else "FAIL", str(message))
        failed |= not good
    console.print(table)
    return int(failed)


def _install_tesseract() -> None:
    if sys.platform == "win32":
        if shutil.which("winget"):
            command = ["winget", "install", "--id", "UB-Mannheim.TesseractOCR", "--exact", "--accept-package-agreements", "--accept-source-agreements"]
        elif shutil.which("choco"):
            command = ["choco", "install", "tesseract", "--yes"]
        else:
            console.print("[yellow]Không tìm thấy winget hoặc Chocolatey.[/]")
            return
    else:
        command = ["brew", "install", "tesseract", "tesseract-lang"] if sys.platform == "darwin" else ["sudo", "apt-get", "install", "-y", "tesseract-ocr", "tesseract-ocr-vie"]
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        console.print(f"[yellow]Không thể tự cài Tesseract: {exc}\nHãy chạy: {_tesseract_hint()}[/]")


def update(*, main: bool = False) -> int:
    code, message = perform_update(main=main)
    console.print(f"[{'green' if code == 0 else 'red'}]{'✓' if code == 0 else 'Lỗi:'} {message}[/]")
    return code


def _tesseract_hint() -> str:
    if sys.platform == "win32": return "winget install UB-Mannheim.TesseractOCR (hoặc mở PowerShell Admin: choco install tesseract -y)"
    if sys.platform == "darwin": return "brew install tesseract tesseract-lang"
    return "sudo apt install tesseract-ocr tesseract-ocr-vie"


def _ocr_languages(command: str) -> set[str]:
    try:
        output = subprocess.run([command, "--list-langs"], capture_output=True, text=True, timeout=10, check=False).stdout
        return {line.strip() for line in output.splitlines()[1:] if line.strip()}
    except OSError:
        return set()


if __name__ == "__main__":
    raise SystemExit(main())
