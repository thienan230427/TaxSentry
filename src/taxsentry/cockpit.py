from __future__ import annotations

import asyncio
import html
import time
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.patch_stdout import patch_stdout
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .bot.telegram_bot import serve as serve_telegram
from .chat_service import SYSTEM as SYSTEM
from .chat_service import ChatService
from .config import describe_config, load_config
from .events import EventType
from .providers import create_provider
from .store import JobStore
from .worker import run_worker

COMMANDS = ["/help", "/status", "/jobs", "/report", "/retry", "/approve", "/new", "/exit"]
LOGO = (
    "╔╦╗╔═╗═╗ ╦╔═╗╔═╗╔╗╔╔╦╗╦═╗╦ ╦",
    " ║ ╠═╣╔╩╦╝╚═╗║╣ ║║║ ║ ╠╦╝╚╦╝",
    " ╩ ╩ ╩╩ ╚═╚═╝╚═╝╝╚╝ ╩ ╩╚═ ╩",
)


def banner_text(settings: dict[str, Any], width: int, unicode: bool = True) -> str:
    provider = settings["provider"]
    model = str(provider.get("model") or "default")
    model = model if len(model) <= 24 else f"{model[:23]}…"
    gmail = settings.get("gmail", {}).get("enabled", True)
    telegram = settings.get("telegram", {}).get("enabled", False)
    if not unicode:
        return "TAXSENTRY · FINANCIAL SENTINEL"
    if width < 70:
        return "◆ TAXSENTRY · FINANCIAL SENTINEL"
    if width < 100:
        return "\n".join((
            "◆ TAXSENTRY · FINANCIAL SENTINEL",
            f"◇ {provider['kind']} / {model}",
            f"● Gmail {'ON' if gmail else 'OFF'}  ·  Telegram {'ON' if telegram else 'OFF'}",
        ))
    status = (
        "◆ Agent      READY",
        f"◇ Provider   {provider['kind']} / {model}",
        f"● Gmail      {'polling ' + str(settings.get('worker', {}).get('poll_seconds', 60)) + 's' if gmail else 'disabled'}",
    )
    lines = [f"{logo:<39}{state}" for logo, state in zip(LOGO, status, strict=True)]
    telegram_status = f"{'●' if telegram else '○'} Telegram {'ON' if telegram else 'OFF'}"
    lines.append(f"{'Trợ lý tài chính và cảnh báo thuế Việt Nam':<57}{telegram_status}")
    return "\n".join(lines)


class Cockpit:
    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = settings or load_config()
        self.console = Console()
        self.unicode = "utf" in (self.console.encoding or "").lower()
        self.chat = ChatService(self.settings, store=JobStore(), provider_factory=create_provider)
        self.store = self.chat.store
        self.history = self.chat.history
        self.state = "IDLE"
        self.stop = asyncio.Event()
        self.tool_started: dict[str, float] = {}
        self.prompt = PromptSession(
            completer=WordCompleter(COMMANDS, ignore_case=True),
            auto_suggest=AutoSuggestFromHistory(),
            enable_history_search=True,
            multiline=False,
        )

    async def run(self) -> int:
        self._header()
        tasks = self._background_tasks()
        try:
            with patch_stdout(raw=True):
                while True:
                    try:
                        text = (await self.prompt.prompt_async(self._prompt_label(), bottom_toolbar=self._toolbar)).strip()
                    except (EOFError, KeyboardInterrupt):
                        return 0
                    if not text:
                        continue
                    if text == "/exit":
                        return 0
                    if text.startswith("/"):
                        await self._command(text)
                        continue
                    await self._turn(text)
        finally:
            self.stop.set()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await self.chat.close()

    @property
    def provider(self):
        return self.chat.provider

    def _background_tasks(self) -> list[asyncio.Task]:
        tasks: list[asyncio.Task] = []
        if self.settings.get("gmail", {}).get("enabled", True):
            tasks.append(asyncio.create_task(self._guard("Gmail worker", run_worker(stop=self.stop, notify=self._worker_notice))))
        if self.settings.get("telegram", {}).get("enabled", False):
            tasks.append(asyncio.create_task(self._guard("Telegram", serve_telegram(self.stop, self.chat, self.notice))))
        return tasks

    async def _guard(self, name: str, task) -> None:
        try:
            await task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._set_state("ERROR")
            self.notice(f"[red]◆ {name} lỗi: {exc}[/]")

    async def _turn(self, text: str) -> None:
        self._set_state("THINKING")
        self.console.print("\n[bold #2dd4bf]◆ SENTRY · ANALYZING[/]")
        self.console.print("[bold #2dd4bf]◆ SENTRY[/] ", end="")
        async for event in self.chat.stream(text):
            if event.type == EventType.TEXT_DELTA:
                self.console.print(event.text, end="", markup=False, soft_wrap=True)
            elif event.type == EventType.TOOL_STARTED:
                self._set_state("TOOL")
                self.tool_started[event.name] = time.perf_counter()
                self.console.print(f"\n[dim]◇ TOOL · {event.name}…[/]")
            elif event.type == EventType.TOOL_COMPLETED:
                elapsed = time.perf_counter() - self.tool_started.pop(event.name, time.perf_counter())
                self.console.print(Panel.fit(f"[green]✓ {elapsed:.1f}s[/]", title=f"TOOL · {event.name}", border_style="#2dd4bf", box=box.ROUNDED if self.unicode else box.ASCII))
            elif event.type == EventType.ERROR:
                self._set_state("ERROR")
                self.console.print(f"\n[red]Lỗi: {event.text}[/]")
        self.console.print()
        if self.state != "ERROR":
            self._set_state("IDLE")

    def _header(self) -> None:
        width = self.console.size.width
        title = f"TAXSENTRY · FINANCIAL SENTINEL · v{__version__}"
        self.console.print(Panel(
            banner_text(self.settings, width, self.unicode),
            title=title,
            border_style="#0891b2",
            box=box.ROUNDED if self.unicode else box.ASCII,
            expand=True,
        ))

    def _prompt_label(self):
        return HTML('<ansicyan>  Sếp › </ansicyan>' if self.unicode else '<ansicyan>  Boss > </ansicyan>')

    def _toolbar(self):
        provider = self.settings["provider"]
        model = provider.get("model") or "default"
        gmail = f"Gmail {'● ' + str(self.settings.get('worker', {}).get('poll_seconds', 60)) + 's' if self.settings.get('gmail', {}).get('enabled', True) else '○'}"
        telegram = f"Telegram {'●' if self.settings.get('telegram', {}).get('enabled', False) else '○'}"
        session = self.chat.session_id[:4]
        value = f"◆ {provider['kind']}/{model} │ {gmail} │ {telegram} │ session {session} │ {self.state}  ·  Enter gửi · /help · Ctrl+C thoát"
        return HTML(f"<ansicyan>{html.escape(value)}</ansicyan>")

    def _set_state(self, state: str) -> None:
        self.state = state
        try:
            self.prompt.app.invalidate()
        except RuntimeError:
            pass

    def notice(self, message: str) -> None:
        self.console.print(f"\n{message}")

    def _worker_notice(self, message: str) -> None:
        self.notice(f"[bold #f59e0b]◆ WORKER[/] · {message}")

    async def _command(self, text: str) -> None:
        command, *args = text.split()
        if command == "/help":
            self.console.print("  ".join(COMMANDS))
        elif command == "/status":
            self.console.print(describe_config(self.settings))
        elif command == "/jobs":
            table = Table("Job", "Trạng thái", "Tiêu đề", "Retry")
            for job in self.store.recent_jobs():
                table.add_row(job["id"][:8], job["state"], job["subject"][:50], str(job["retries"]))
            self.console.print(table)
        elif command == "/report":
            latest = self.store.latest_report()
            self.console.print(latest["payload"]["executive_summary"] if latest else "Chưa có báo cáo.")
        elif command == "/new":
            self.chat.new_session()
            self.console.print("[green]✓ Đã mở phiên hội thoại mới.[/]")
        elif command in {"/retry", "/approve"}:
            job = self.store.resolve(args[0] if args else "")
            valid = {"needs_review"} if command == "/approve" else {"failed", "needs_review"}
            if not job or job["state"] not in valid:
                self.console.print("Không tìm thấy job Failed/NeedsReview phù hợp.")
            else:
                approved = command == "/approve"
                self.store.requeue(job["id"], approved=approved)
                self.console.print(f"[green]✓ Đã {'duyệt' if approved else 'xếp lại'} job {job['id'][:8]}.[/]")
        else:
            self.console.print("Lệnh chưa hỗ trợ. Dùng /help.")
