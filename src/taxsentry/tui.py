from __future__ import annotations

import argparse
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
from .ui_text import text as ui_text
from .updater import perform_update

console = Console()


def _parser(settings: dict | None = None) -> argparse.ArgumentParser:
    en = (settings or {}).get("ui", {}).get("language") == "en"
    parser = argparse.ArgumentParser(prog="taxsentry", description="TaxSentry — Financial Sentinel TUI")
    parser.add_argument("--version", action="version", version=f"TaxSentry {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("setup", help="configure provider, Gmail, and Telegram" if en else "cấu hình provider, Gmail và Telegram")
    sub.add_parser("status", help="show configuration and integration status" if en else "hiển thị cấu hình và trạng thái tích hợp")
    doctor_parser = sub.add_parser("doctor", help="check integrations" if en else "kiểm tra các tích hợp")
    doctor_parser.add_argument("--fix", action="store_true")
    update_parser = sub.add_parser("update", help="update TaxSentry" if en else "cập nhật TaxSentry")
    update_parser.add_argument("--main", action="store_true", help="update core from GitHub main" if en else "cập nhật core từ GitHub main")
    return parser


def main(argv: list[str] | None = None) -> int:
    settings = load_config()
    args = _parser(settings).parse_args(argv)
    if args.command == "setup":
        return setup()
    if args.command == "status":
        console.print(describe_config(settings))
        return 0
    if args.command == "doctor":
        return doctor(fix=args.fix)
    if args.command == "update":
        return update(main=args.main)
    if not settings.get("configured"):
        code = setup()
        settings = load_config()
        if code or not settings.get("configured"):
            return code
    return Cockpit(settings).run() or 0


def setup() -> int:
    config = load_config()
    try:
        selection = run_setup_wizard(config, console)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        return 2
    if selection is None:
        console.print(f"[yellow]{ui_text(config, 'setup_cancelled')}[/]")
        return 0
    backup = backup_v1_profile()
    if backup:
        message = f"Backed up the v1 profile: {backup}" if selection.config.get("ui", {}).get("language") == "en" else f"Đã sao lưu profile v1: {backup}"
        console.print(f"[yellow]{message}[/]")
    return authenticate_selection(selection, console)


def doctor(*, fix: bool = False) -> int:
    settings, failed = load_config(), False
    en = settings.get("ui", {}).get("language") == "en"
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
        missing_text = f"Missing {missing}" if en else f"Thiếu {missing}"
        checks.append(("Tesseract", bool(tesseract) and not missing, tesseract if not missing else f"{missing_text}; {_tesseract_hint()}"))
        gmail_account = settings["gmail"].get("account") or "default"
        try:
            gmail_token = get_secret(f"gmail-app-password:{gmail_account}")
        except keyring.errors.KeyringError:
            gmail_token = ""
        checks.append(("Gmail App Password", bool(gmail_token), ("stored in keyring" if en else "đã lưu trong keyring") if gmail_token else "run `taxsentry setup`"))
        marker = settings["gmail"].get("process_after_uids") or settings["gmail"].get("process_after_uid")
        checks.append(("Gmail sender policy" if en else "Chính sách người gửi Gmail", True, "all senders; automatic processing only after setup marker" if en else "mọi người gửi; chỉ tự động xử lý sau mốc setup"))
        checks.append(("Gmail worker marker", marker is not None, str(marker) if marker is not None else "run `taxsentry setup`"))
        libreoffice = shutil.which("soffice")
        checks.append(("LibreOffice", True, libreoffice or ("optional; required only for .doc/.xls/.ppt" if en else "tùy chọn; chỉ cần cho .doc/.xls/.ppt")))
    else:
        checks.append(("Gmail + OCR", True, "SKIP — disabled by setup profile" if en else "BỎ QUA — profile đã tắt"))
    telegram_required = bool(settings.get("telegram", {}).get("enabled"))
    try:
        telegram_token = get_secret("telegram:bot-token") if telegram_required else "disabled"
    except keyring.errors.KeyringError:
        telegram_token = ""
    checks.append(("Telegram", not telegram_required or bool(telegram_token), ("configured" if en else "đã cấu hình") if telegram_token and telegram_required else str(telegram_token)))
    checks.append(("Data directory" if en else "Thư mục dữ liệu", APP_HOME.is_dir() and os.access(APP_HOME, os.W_OK), str(APP_HOME)))
    table = Table("Check" if en else "Kiểm tra", "Status" if en else "Trạng thái", "Detail" if en else "Chi tiết")
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
