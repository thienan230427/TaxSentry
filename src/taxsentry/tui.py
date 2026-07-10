from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from .cockpit import Cockpit
from .config import backup_v1_profile, describe_config, load_config, save_config
from .gmail import GmailClient
from .providers import CodexAppServerProvider, from_settings, health_check
from .secrets import delete_secret, set_secret
from .service_control import service
from .store import JobStore
from .worker import run_worker

console = Console()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="taxsentry", description="TaxSentry v2 — AI Agent cho Giám đốc")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("chat")
    sub.add_parser("setup")
    sub.add_parser("status")
    sub.add_parser("doctor")
    sub.add_parser("jobs")
    report = sub.add_parser("report")
    report.add_argument("--send", action="store_true")
    worker = sub.add_parser("worker")
    worker.add_argument("action", choices=["run"])
    worker.add_argument("--once", action="store_true")
    auth = sub.add_parser("auth")
    auth.add_argument("provider", choices=["codex", "gmail", "telegram", "status", "logout"])
    auth.add_argument("--device-code", action="store_true")
    svc = sub.add_parser("service")
    svc.add_argument("action", choices=["install", "start", "stop", "status", "remove", "logs"])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in {None, "chat"}:
        return asyncio.run(Cockpit().run())
    if args.command == "setup":
        return setup()
    if args.command == "status":
        console.print(describe_config(load_config()))
        return 0
    if args.command == "doctor":
        return doctor()
    if args.command == "jobs":
        return jobs()
    if args.command == "report":
        return report(send=args.send)
    if args.command == "worker":
        return asyncio.run(run_worker(once=args.once))
    if args.command == "auth":
        return auth(args.provider, args.device_code)
    if args.command == "service":
        console.print(service(args.action))
        return 0
    return 2


def setup() -> int:
    backup = backup_v1_profile()
    if backup:
        console.print(f"[yellow]Đã backup profile v1: {backup}[/]")
    config = load_config()
    config["gmail"]["account"] = Prompt.ask("Gmail nội bộ dùng để nhận báo cáo", default=config["gmail"].get("account", ""))
    config["gmail"]["oauth_client_file"] = Prompt.ask("Đường dẫn OAuth Desktop credentials.json", default=config["gmail"].get("oauth_client_file", ""))
    senders = Prompt.ask("Email Kế toán trưởng (phân cách dấu phẩy)", default=",".join(config["gmail"].get("trusted_senders", [])))
    config["gmail"]["trusted_senders"] = [item.strip().casefold() for item in senders.split(",") if item.strip()]
    config["director"]["email"] = Prompt.ask("Email Giám đốc", default=config["director"].get("email", ""))
    chats = Prompt.ask("Telegram chat ID Giám đốc (phân cách dấu phẩy)", default=",".join(map(str, config["director"].get("telegram_chat_ids", []))))
    config["director"]["telegram_chat_ids"] = [item.strip() for item in chats.split(",") if item.strip()]
    config["provider"]["kind"] = Prompt.ask("Provider", choices=["codex", "lmstudio"], default=config["provider"].get("kind", "lmstudio"))
    config["provider"]["model"] = Prompt.ask("Model (để trống dùng mặc định)", default=config["provider"].get("model", ""))
    config["worker"]["poll_seconds"] = IntPrompt.ask("Chu kỳ quét Gmail (giây)", default=int(config["worker"].get("poll_seconds", 60)))
    config["configured"] = True
    save_config(config)
    console.print("[green]✓ Đã tạo profile TaxSentry v2 sạch.[/]")
    return 0


def auth(provider: str, device_code: bool = False) -> int:
    settings = load_config()
    if provider == "gmail":
        GmailClient(settings).authenticate()
        console.print("[green]✓ Gmail OAuth connected.[/]")
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
                    if result.get("verificationUrl"):
                        console.print(f"Mở {result['verificationUrl']} và nhập mã [bold]{result['userCode']}[/]")
                await client.login(device_code=device_code, challenge=show)
            finally:
                await client.close()
        asyncio.run(login())
        settings["provider"]["kind"] = "codex"
        settings["provider"]["auth_mode"] = "codex"
        save_config(settings)
        console.print("[green]✓ Codex connected through official app-server.[/]")
    elif provider == "logout":
        account = settings["gmail"].get("account") or "default"
        delete_secret(f"gmail:{account}")
        delete_secret("telegram:bot-token")
        console.print("Đã xóa Gmail/Telegram secrets của TaxSentry. Dùng `codex logout` để đăng xuất Codex.")
    else:
        console.print(describe_config(settings))
    return 0


def doctor() -> int:
    settings, failed = load_config(), False
    checks = []
    ok, detail = health_check(from_settings(settings))
    checks.append(("Provider", ok, detail))
    tesseract = shutil.which("tesseract")
    checks.append(("Tesseract", bool(tesseract), tesseract or _tesseract_hint()))
    oauth_file = Path(settings["gmail"].get("oauth_client_file", ""))
    checks.append(("Gmail OAuth client", oauth_file.is_file(), str(oauth_file) if oauth_file else "not configured"))
    checks.append(("Trusted senders", bool(settings["gmail"].get("trusted_senders")), str(settings["gmail"].get("trusted_senders", []))))
    table = Table("Check", "Status", "Detail")
    for name, good, message in checks:
        table.add_row(name, "OK" if good else "FAIL", str(message))
        failed |= not good
    console.print(table)
    return int(failed)


def _tesseract_hint() -> str:
    if sys.platform == "win32": return "winget install UB-Mannheim.TesseractOCR"
    if sys.platform == "darwin": return "brew install tesseract tesseract-lang"
    return "sudo apt install tesseract-ocr tesseract-ocr-vie"


def jobs() -> int:
    table = Table("Job", "State", "Sender", "Subject", "Retry")
    for item in JobStore().recent_jobs():
        table.add_row(item["id"][:8], item["state"], item["sender"], item["subject"][:40], str(item["retries"]))
    console.print(table)
    return 0


def report(*, send: bool = False) -> int:
    latest = JobStore().latest_report()
    if not latest:
        console.print("Chưa có báo cáo.")
        return 1
    console.print(json.dumps(latest["payload"], ensure_ascii=False, indent=2))
    if send:
        if not Confirm.ask("Gửi lại báo cáo này cho Giám đốc?"):
            return 0
        console.print("Dùng `/retry` trong workflow khi cần gửi lại đầy đủ; v2 không gửi thủ công nếu thiếu Gmail message context.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
