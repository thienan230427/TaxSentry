from __future__ import annotations

from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import describe_config, load_config, save_config
from .events import EventType
from .providers import create_provider
from .store import JobStore

COMMANDS = ["/help", "/status", "/jobs", "/latest", "/report", "/provider", "/auth", "/retry", "/approve", "/clear", "/exit"]
SYSTEM = "Bạn là TaxSentry, trợ lý CFO và thuế Việt Nam. Xưng em, gọi người dùng là Sếp. Chỉ kết luận từ dữ liệu có thật, luôn nêu độ tin cậy và để Giám đốc quyết định cuối cùng."


class Cockpit:
    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = settings or load_config()
        self.console = Console()
        self.store = JobStore()
        self.provider = create_provider(self.settings)
        self.history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM}]
        self.prompt = PromptSession(completer=WordCompleter(COMMANDS, ignore_case=True), auto_suggest=AutoSuggestFromHistory(), enable_history_search=True, multiline=False)

    async def run(self) -> int:
        self._header()
        try:
            while True:
                try:
                    text = (await self.prompt.prompt_async(HTML('<ansicyan>Sếp</ansicyan> <ansiblue>›</ansiblue> '), bottom_toolbar=self._toolbar)).strip()
                except (EOFError, KeyboardInterrupt):
                    return 0
                if not text:
                    continue
                if text in {"/exit", "/quit"}:
                    return 0
                if text.startswith("/"):
                    await self._command(text)
                    continue
                self.history.append({"role": "user", "content": text})
                self.console.print("[bold #38bdf8]TaxSentry ›[/] ", end="")
                chunks: list[str] = []
                async for event in self.provider.stream_turn(self.history):
                    if event.type == EventType.TEXT_DELTA:
                        chunks.append(event.text)
                        self.console.print(event.text, end="", markup=False, soft_wrap=True)
                    elif event.type == EventType.TOOL_STARTED:
                        self.console.print(f"\n[dim]● {event.name}…[/]")
                    elif event.type == EventType.TOOL_COMPLETED:
                        self.console.print(f"[green]✓ {event.name}[/]")
                    elif event.type == EventType.ERROR:
                        self.console.print(f"\n[red]Lỗi: {event.text}[/]")
                self.console.print()
                if chunks:
                    self.history.append({"role": "assistant", "content": "".join(chunks)})
        finally:
            await self.provider.close()

    def _header(self) -> None:
        provider = self.settings["provider"]
        model = provider.get("model") or "mặc định"
        self.console.print(Panel.fit(f"[bold #38bdf8]◆ TaxSentry v2[/]\n[dim]AI Agent cho Giám đốc · {provider['kind']} / {model}[/]", border_style="#0ea5e9"))

    def _toolbar(self):
        configured = "ready" if self.settings.get("configured") else "setup required"
        return HTML(f'<ansicyan>{self.settings["provider"]["kind"]}</ansicyan>  <ansigray>{configured} · /help · Ctrl+C thoát</ansigray>')

    async def _command(self, text: str) -> None:
        command, *args = text.split()
        if command == "/help":
            self.console.print("  ".join(COMMANDS))
        elif command in {"/status", "/auth"}:
            self.console.print(describe_config(self.settings))
        elif command == "/jobs":
            table = Table("Job", "Trạng thái", "Tiêu đề", "Retry")
            for job in self.store.recent_jobs():
                table.add_row(job["id"][:8], job["state"], job["subject"][:50], str(job["retries"]))
            self.console.print(table)
        elif command in {"/latest", "/report"}:
            latest = self.store.latest_report()
            self.console.print(latest["payload"]["executive_summary"] if latest else "Chưa có báo cáo.")
        elif command == "/provider":
            selected = args[0] if args else ("codex" if self.settings["provider"]["kind"] == "lmstudio" else "lmstudio")
            if selected not in {"codex", "lmstudio"}:
                self.console.print("Dùng /provider codex hoặc /provider lmstudio")
                return
            self.settings["provider"]["kind"] = selected
            self.settings["provider"]["auth_mode"] = selected
            save_config(self.settings)
            await self.provider.close()
            self.provider = create_provider(self.settings)
            self.console.print(f"[green]Đã chuyển sang {selected}[/]")
        elif command == "/clear":
            self.history = self.history[:1]
            self.console.print("Đã xóa context hội thoại; transcript terminal được giữ nguyên.")
        elif command in {"/retry", "/approve"}:
            job = self.store.resolve(args[0] if args else "")
            if not job or job["state"] not in ({"needs_review"} if command == "/approve" else {"failed", "needs_review"}):
                self.console.print("Không tìm thấy job Failed/NeedsReview phù hợp.")
            else:
                approved = command == "/approve"
                self.store.requeue(job["id"], approved=approved)
                self.console.print(f"[green]✓ Đã {'duyệt' if approved else 'xếp lại'} job {job['id'][:8]}.[/]")
        else:
            self.console.print("Lệnh chưa hỗ trợ. Dùng /help.")
