from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import shutil
import subprocess
import sys
import uuid
import webbrowser
from pathlib import Path

import keyring
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from .cockpit import Cockpit
from .config import APP_HOME, backup_v1_profile, describe_config, ensure_directories, load_config, save_config
from .control_server import DashboardAuth, run_dashboard
from .gmail import GmailClient
from .providers import CodexAppServerProvider, from_settings, health_check
from .reporting import html_summary
from .secrets import delete_secret, get_secret, set_secret
from .service_control import service
from .setup_wizard import authenticate_selection, run_setup_wizard
from .store import JobStore
from .telegram import TelegramDirector
from .updater import perform_update
from .worker import run_worker

console = Console()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taxsentry", description="TaxSentry v2 — AI Agent cho Giám đốc")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("chat")
    for name in ("start", "dashboard"):
        dashboard = sub.add_parser(name)
        dashboard.add_argument("--no-open", action="store_true")
        dashboard.add_argument("--port", type=int, default=None)
    sub.add_parser("gateway")
    update_parser = sub.add_parser("update")
    update_parser.add_argument("--main", action="store_true", help="cập nhật core từ GitHub main")
    sub.add_parser("setup")
    sub.add_parser("status")
    doctor_parser = sub.add_parser("doctor")
    doctor_parser.add_argument("--fix", action="store_true")
    sub.add_parser("jobs")
    report = sub.add_parser("report")
    report.add_argument("--send", action="store_true")
    worker = sub.add_parser("worker")
    worker.add_argument("action", choices=["run"])
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--gateway", action="store_true")
    auth = sub.add_parser("auth")
    auth.add_argument("provider", choices=["codex", "gmail", "telegram", "dashboard", "status", "logout"])
    auth.add_argument("--device-code", action="store_true")
    auth.add_argument("--show", action="store_true")
    auth.add_argument("--rotate", action="store_true")
    svc = sub.add_parser("service")
    svc.add_argument("action", choices=["install", "start", "stop", "status", "remove", "logs"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "chat":
        return asyncio.run(Cockpit().run())
    if args.command in {None, "start", "dashboard"}:
        settings = load_config()
        return run_dashboard(
            port=getattr(args, "port", None) or int(settings["ui"].get("port", 8765)),
            open_browser=not getattr(args, "no_open", False),
        )
    if args.command == "gateway":
        from .bot.telegram_bot import main as run_gateway

        run_gateway()
        return 0
    if args.command == "update":
        return update(main=args.main)
    if args.command == "setup":
        return setup()
    if args.command == "status":
        console.print(describe_config(load_config()))
        return 0
    if args.command == "doctor":
        return doctor(fix=args.fix)
    if args.command == "jobs":
        return jobs()
    if args.command == "report":
        return report(send=args.send)
    if args.command == "worker":
        return asyncio.run(run_worker(once=args.once, gateway=args.gateway))
    if args.command == "auth":
        return auth(args.provider, args.device_code, show=args.show, rotate=args.rotate)
    if args.command == "service":
        console.print(service(args.action))
        return 0
    return 2


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


def auth(provider: str, device_code: bool = False, *, show: bool = False, rotate: bool = False) -> int:
    settings = load_config()
    if provider == "gmail":
        password = getpass.getpass("Gmail App Password (16 characters): ")
        GmailClient(settings).authenticate(app_password=password)
        save_config(settings)
        console.print("[green]✓ Gmail connected with App Password.[/]")
    elif provider == "telegram":
        set_secret("telegram:bot-token", getpass.getpass("Telegram bot token: "))
        settings["telegram"]["enabled"] = True
        settings["integrations"]["telegram"]["enabled"] = True
        save_config(settings)
        console.print("[green]✓ Telegram token stored in OS keyring.[/]")
    elif provider == "codex":
        async def login():
            client = CodexAppServerProvider(model=settings["provider"].get("model", ""))
            try:
                def show(result):
                    if result.get("authUrl"):
                        console.print(f"Mở trình duyệt: {result['authUrl']}")
                        webbrowser.open(result["authUrl"])
                    if result.get("verificationUrl"):
                        console.print(f"Mở {result['verificationUrl']} và nhập mã [bold]{result['userCode']}[/]")
                        webbrowser.open(result["verificationUrl"])
                await client.login(device_code=device_code, challenge=show)
            finally:
                await client.close()
        asyncio.run(login())
        settings["provider"]["kind"] = "codex"
        settings["provider"]["auth_mode"] = "codex"
        save_config(settings)
        console.print("[green]✓ Codex connected through official app-server.[/]")
    elif provider == "dashboard":
        dashboard_auth = DashboardAuth()
        token = dashboard_auth.rotate() if rotate else dashboard_auth.token
        if show or rotate:
            console.print(f"Dashboard token: [bold]{token}[/]")
        else:
            console.print("Dashboard token đã sẵn sàng. Dùng `taxsentry auth dashboard --show` để xem hoặc `--rotate` để đổi.")
    elif provider == "logout":
        account = settings["gmail"].get("account") or "default"
        delete_secret(f"gmail:{account}")
        delete_secret(f"gmail-app-password:{account}")
        delete_secret("telegram:bot-token")
        async def logout_codex():
            client = CodexAppServerProvider()
            try:
                await client.logout()
            finally:
                await client.close()
        try:
            asyncio.run(logout_codex())
            console.print("Đã xóa Gmail/Telegram secrets và phiên Codex riêng của TaxSentry.")
        except Exception as exc:
            console.print(f"[yellow]Đã xóa Gmail/Telegram secrets; chưa thể đăng xuất Codex: {exc}[/]")
    else:
        console.print(describe_config(settings))
    return 0


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
        checks.append(("Tesseract", bool(tesseract) and required_languages <= ocr_languages, tesseract if required_languages <= ocr_languages else f"Thiếu {sorted(required_languages - ocr_languages)}; {_tesseract_hint()}"))
        gmail_account = settings["gmail"].get("account") or "default"
        try:
            gmail_token = get_secret(f"gmail-app-password:{gmail_account}")
        except keyring.errors.KeyringError:
            gmail_token = ""
        checks.append(("Gmail App Password", bool(gmail_token), "stored in keyring" if gmail_token else "run `taxsentry auth gmail`"))
        checks.append(("Trusted senders", bool(settings["gmail"].get("trusted_senders")), str(settings["gmail"].get("trusted_senders", []))))
        checks.append(("Director email", bool(settings["director"].get("email")), settings["director"].get("email") or "not configured"))
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


def jobs() -> int:
    table = Table("Job", "State", "Sender", "Subject", "Retry")
    for item in JobStore().recent_jobs():
        table.add_row(item["id"][:8], item["state"], item["sender"], item["subject"][:40], str(item["retries"]))
    console.print(table)
    return 0


def report(*, send: bool = False) -> int:
    store = JobStore()
    latest = store.latest_report()
    if not latest:
        console.print("Chưa có báo cáo.")
        return 1
    console.print(json.dumps(latest["payload"], ensure_ascii=False, indent=2))
    if send:
        if not Confirm.ask("Gửi lại báo cáo này cho Giám đốc?"):
            return 0
        settings = load_config()
        pdf = Path(latest["pdf_path"])
        director = settings["director"].get("email", "")
        if not director or not pdf.is_file():
            console.print("[red]Thiếu director.email hoặc file PDF báo cáo.[/]")
            return 1
        outgoing = GmailClient(settings).send_report(director, f"TaxSentry gửi lại: {latest['subject']}", html_summary(latest["payload"]), pdf, idempotency_key=f"{latest['job_id']}-manual-{uuid.uuid4()}")
        store.delivery(latest["job_id"], "gmail", "sent", outgoing)
        telegram_ids = asyncio.run(TelegramDirector(settings).notify(f"📄 Gửi lại: {latest['payload']['executive_summary']}", pdf))
        for external_id in telegram_ids:
            store.delivery(latest["job_id"], "telegram", "sent", external_id)
        console.print("[green]✓ Đã gửi lại báo cáo.[/]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
