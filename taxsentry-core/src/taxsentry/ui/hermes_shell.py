from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import CompleteStyle
except Exception:  # pragma: no cover - graceful fallback if dependency is missing
    PromptSession = None
    AutoSuggestFromHistory = None
    WordCompleter = None
    HTML = None
    CompleteStyle = None

from taxsentry.agent import AgentKernel, AgentMode, ProviderPreset
from taxsentry.config import get_value, load_config
from .dashboard import TaxSentryDashboard

console = Console()

SLASH_COMMANDS = [
    "/help",
    "/status",
    "/memory",
    "/remember",
    "/mode",
    "/provider",
    "/audit",
    "/dashboard",
    "/tools",
    "/trace",
    "/jobs",
    "/replay",
    "/exit",
]

MODE_HINTS = {
    AgentMode.CHAT: ["/help", "/status", "/memory", "/provider", "/dashboard", "/exit"],
    AgentMode.ANALYZE: ["/audit", "/tools", "/trace", "/jobs", "/replay", "/mode chat"],
    AgentMode.EXECUTE: ["/status", "/provider", "/dashboard", "/jobs", "/trace", "/exit"],
    AgentMode.REVIEW: ["/audit", "/status", "/jobs", "/replay", "/dashboard", "/exit"],
    AgentMode.SETUP: ["/provider", "/mode chat", "/dashboard", "/exit"],
}


@dataclass
class HermesFrame:
    header: Panel
    left: Panel
    center: Panel
    right: Panel
    footer: Panel


class HermesShell:
    def __init__(self, settings: dict[str, Any] | None = None):
        self.settings = settings or load_config()
        self.kernel = AgentKernel(self.settings, session_entry_point="tui", session_mode=AgentMode.CHAT)
        self._last_frame_note = "Ready"
        self._last_turn: Any | None = None
        self._prompt_session = self._create_prompt_session()

    def run(self) -> int:
        self._show_provider_picker()
        self._sync_kernel_provider()
        self._render_screen(initial=True)

        while True:
            try:
                user_text = self._prompt_user().strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\nExiting...")
                return 0

            if not user_text:
                self._render_screen()
                continue

            if user_text in {"/exit", "/quit", "/q"}:
                console.print("Goodbye ✨")
                return 0

            if user_text.startswith("/mode "):
                mode_name = user_text.split(" ", 1)[1].strip()
                self.kernel.set_mode(self._parse_mode(mode_name))
                self._last_frame_note = f"Mode switched to {self.kernel.state.mode.value}"
                self._render_screen()
                continue

            if user_text == "/provider":
                self._show_provider_picker()
                self._sync_kernel_provider()
                self._last_frame_note = "Provider updated"
                self._render_screen()
                continue

            if user_text == "/dashboard":
                dashboard = TaxSentryDashboard(self.kernel.runtime_service)
                self._last_frame_note = "Dashboard opened"
                dashboard.run()
                self._render_screen()
                continue

            result = self.kernel.handle(user_text, progress_callback=self._on_progress)
            self._last_turn = result
            self._last_frame_note = result.route
            self._render_screen(last_result=result.response.text)

    def _create_prompt_session(self):
        if PromptSession is None:
            return None

        completer = WordCompleter(SLASH_COMMANDS, ignore_case=True, match_middle=True)
        return PromptSession(
            completer=completer,
            auto_suggest=AutoSuggestFromHistory(),
            complete_while_typing=True,
            enable_history_search=True,
            complete_style=CompleteStyle.MULTI_COLUMN,
            reserve_space_for_menu=8,
        )

    def _prompt_user(self) -> str:
        if self._prompt_session is None or HTML is None:
            return input("\nSếp > ")

        return self._prompt_session.prompt(
            HTML('<ansicyan>Sếp</ansicyan> <ansiblue>></ansiblue> '),
            bottom_toolbar=self._build_prompt_toolbar,
        )

    def _build_prompt_toolbar(self):
        hints = self._command_hints()
        chips = "  ".join(f"[{hint}]" for hint in hints)
        return HTML(
            f'<ansigray>Gợi ý:</ansigray> <ansicyan>{chips}</ansicyan> '
            '<ansigray>| Tab để xem thêm lệnh</ansigray>'
        )

    def _command_hints(self) -> list[str]:
        mode_hints = list(MODE_HINTS.get(self.kernel.state.mode, MODE_HINTS[AgentMode.CHAT]))
        if self._last_turn is not None and getattr(self._last_turn, "route", "") == "analysis":
            return ["/audit", "/tools", "/trace", "/jobs", "/replay", "/dashboard"]
        return mode_hints

    def _show_provider_picker(self) -> None:
        presets = self.kernel.available_provider_presets()
        console.clear()
        console.print(self._build_provider_picker_panel(presets))
        choice = Prompt.ask("Select provider by number", default="1")
        try:
            selected = presets[max(0, min(len(presets) - 1, int(choice) - 1))]
        except Exception:
            selected = presets[0]
        if not selected.available:
            console.print(Panel(f"{selected.label} is unavailable right now.", border_style="red"))
            selected = presets[0]
        self.kernel.apply_provider_preset(selected, persist=True)

    def _sync_kernel_provider(self) -> None:
        self.settings = self.kernel.settings

    def _on_progress(self, stage: str, payload: dict[str, Any]) -> None:
        progress = payload.get("progress") if isinstance(payload, dict) else None
        if stage == "plan_start":
            self._last_frame_note = f"Planning {payload.get('plan', '')}"
        elif stage == "plan_step":
            step_title = payload.get("step_title", payload.get("tool_name", "step"))
            self._last_frame_note = f"Running {progress or '?'}: {step_title}"
        elif stage == "plan_complete":
            self._last_frame_note = f"Plan complete {payload.get('plan', '')}"
        if progress:
            self._render_screen()

    def _render_screen(self, *, initial: bool = False, last_result: str = "") -> None:
        console.clear()
        frame = self._build_frame(last_result=last_result, initial=initial)
        layout = Layout()
        layout.split_column(
            Layout(frame.header, size=5),
            Layout(frame.center, ratio=1),
            Layout(frame.footer, size=5),
        )
        console.print(layout)

    def _build_frame(self, *, last_result: str, initial: bool) -> HermesFrame:
        snapshot = self.kernel.snapshot()
        header = self._build_header_panel(snapshot)
        left = self._build_left_rail(snapshot)
        center = self._build_center_panel(snapshot, last_result=last_result, initial=initial)
        right = self._build_right_rail(snapshot)
        footer = self._build_footer_panel(snapshot)
        return HermesFrame(header=header, left=left, center=center, right=right, footer=footer)

    def _build_provider_picker_panel(self, presets: list[ProviderPreset]) -> Panel:
        table = Table.grid(expand=True)
        table.add_column()
        header = Text()
        header.append("Select provider:\n", style="bold yellow")
        header.append("Select by number, Enter to confirm.\n\n", style="dim")
        for index, preset in enumerate(presets, start=1):
            active = preset.key == self.kernel.state.provider_key
            marker = "(o)" if not active else "(•)"
            color = "green" if active else ("white" if preset.available else "red")
            badge = f" <{preset.badge}>" if preset.badge else ""
            availability = "" if preset.available else " [unavailable]"
            header.append(f"{marker} {index}. {preset.label}{badge} ({preset.description}){availability}\n", style=color)
        table.add_row(header)
        return Panel(table, border_style="yellow", title="Provider Select")

    def _build_header_panel(self, snapshot: dict[str, Any]) -> Panel:
        provider = snapshot["provider"]
        provider_health = snapshot["provider_health"]
        state = snapshot["state"]
        title = Text()
        title.append("TaxSentry TUI", style="bold white")
        title.append("  ")
        title.append(
            f"{get_value(self.settings, 'agent.name', 'TaxSentry')}",
            style="cyan",
        )
        title.append("\n")
        title.append(f"mode={state.mode.value}", style="magenta")
        title.append(" | ")
        title.append(f"provider={snapshot['provider_label']}", style="green")
        title.append(" | ")
        title.append(f"model={provider.model}", style="yellow")
        title.append(" | ")
        title.append(f"health={'OK' if provider_health[0] else 'FAIL'}", style="bold green" if provider_health[0] else "bold red")
        title.append(" | ")
        title.append(f"session={state.session_id[:8]}", style="dim")
        return Panel(title, border_style="cyan", style="bold white on black", box=box.SQUARE)

    def _build_left_rail(self, snapshot: dict[str, Any]) -> Panel:
        presets = self.kernel.available_provider_presets()
        table = Table.grid(expand=True)
        table.add_column()

        provider_block = Text()
        provider_block.append("Providers\n", style="bold yellow")
        for index, preset in enumerate(presets, start=1):
            active = preset.key == self.kernel.state.provider_key
            marker = "▶" if active else "•"
            color = "green" if active else ("white" if preset.available else "red")
            provider_block.append(f"{marker} {index}. {preset.label}\n", style=color)
            provider_block.append(f"    {preset.description}\n", style="dim")

        actions = Text()
        actions.append("\nActions\n", style="bold yellow")
        for line in [
            "/help, /status, /memory",
            "/remember <text>",
            "/mode chat|analysis|execute|review|setup",
            "/provider",
            "/audit",
            "/dashboard",
            "/jobs",
            "/replay [session_id]",
            "/exit",
        ]:
            actions.append(f"• {line}\n", style="white")

        sessions = Text()
        sessions.append("\nRecent sessions\n", style="bold yellow")
        session = snapshot["session"]
        sessions.append(f"• Current: {session.session_id[:8]} ({session.mode})\n", style="white")
        sessions.append(f"• Started: {session.started_at}\n", style="dim")
        sessions.append(f"• Turns: {len(session.messages)}\n", style="dim")

        table.add_row(provider_block)
        table.add_row(actions)
        table.add_row(sessions)
        return Panel(table, title="Left Rail", border_style="cyan", box=box.ROUNDED)

    def _build_center_panel(self, snapshot: dict[str, Any], *, last_result: str, initial: bool) -> Panel:
        state = snapshot["state"]
        active_plan = snapshot.get("active_plan") or "No active plan"
        toolchain = snapshot.get("toolchain") or []
        turn_plan = getattr(self._last_turn, "plan", "") if self._last_turn is not None else ""
        turn_toolchain = getattr(self._last_turn, "toolchain", []) if self._last_turn is not None else []
        body = Text()
        body.append("Conversation stream\n", style="bold #f0a27a")
        body.append(f"gateway connected | {self._last_frame_note}\n", style="dim")
        body.append(f"plan={active_plan} | progress={state.last_progress or '-'}\n", style="dim")
        body.append(f"tools={', '.join(toolchain) if toolchain else '-'}\n\n", style="dim")
        if turn_plan:
            body.append(f"Turn plan: {turn_plan}\n", style="dim")
        if turn_toolchain:
            body.append(f"Turn tools: {', '.join(turn_toolchain)}\n", style="dim")

        if initial:
            body.append("Ready for the first request.\n", style="white")
            body.append("Type / then Tab to open slash command suggestions.\n", style="cyan")
            body.append("\n")
            body.append("Suggested flow:\n", style="bold white")
            for command in self._command_hints():
                body.append(f"  {command}\n", style="white")
        elif last_result:
            if state.last_user_input:
                body.append("Sếp\n", style="bold cyan")
                body.append(f" {state.last_user_input} \n\n", style="white on grey23")
            body.append("TaxSentry\n", style="bold green")
            body.append(last_result[:1200], style="white")
            if self._last_turn is not None:
                hints = getattr(self._last_turn, "hints", []) or []
                confidence = getattr(self._last_turn, "response", None)
                if hints:
                    body.append(f"\nHints: {', '.join(hints)}\n", style="dim")
                if confidence is not None:
                    body.append(
                        f"Route confidence: {getattr(confidence, 'confidence', 0.0):.2f}\n",
                        style="dim",
                    )
        else:
            body.append("Waiting for the next action.\n", style="dim")

        return Panel(body, title="Chat", border_style="grey39", box=box.SQUARE)

    def _build_right_rail(self, snapshot: dict[str, Any]) -> Panel:
        memory_facts = snapshot["memory_facts"]
        recent_reports = snapshot["recent_reports"]
        recent_jobs = snapshot.get("recent_jobs") or []
        evidence_context = snapshot["evidence_context"]
        recent_events = snapshot.get("recent_events") or []
        recent_sessions = snapshot.get("recent_sessions") or []

        body = Text()
        body.append("Right Rail\n", style="bold yellow")
        body.append("Memory snippets\n", style="bold cyan")
        if memory_facts:
            for item in memory_facts[:4]:
                body.append(f"• {item.get('summary') or item.get('text')}\n", style="white")
        else:
            body.append("• No memory facts yet\n", style="dim")

        body.append("\nRecent reports\n", style="bold cyan")
        if recent_reports:
            for row in recent_reports[:3]:
                body.append(f"• {row.get('file_name')} | {row.get('tax_risk_status')}\n", style="white")
        else:
            body.append("• No reports yet\n", style="dim")

        body.append("\nRecent jobs\n", style="bold cyan")
        if recent_jobs:
            for job in recent_jobs[:3]:
                body.append(
                    f"• {job.get('job_id', 'n/a')[:8]} | {job.get('job_type', 'n/a')} | {job.get('state', 'n/a')}\n",
                    style="white",
                )
        else:
            body.append("• No jobs yet\n", style="dim")

        body.append("\nRecent sessions\n", style="bold cyan")
        if recent_sessions:
            for session in recent_sessions[:3]:
                body.append(
                    f"• {session.get('session_id', 'n/a')[:8]} | {session.get('mode', 'n/a')} | {session.get('outcome') or 'open'}\n",
                    style="white",
                )
        else:
            body.append("• No sessions yet\n", style="dim")

        body.append("\nTrace preview\n", style="bold cyan")
        if evidence_context:
            body.append(f"• {evidence_context.get('source_file', 'n/a')}\n", style="white")
            body.append(f"• session={evidence_context.get('session_id', 'n/a')}\n", style="dim")
            body.append(f"• trace={evidence_context.get('trace_id', 'n/a')}\n", style="dim")
        elif snapshot.get("trace_replay"):
            for line in snapshot["trace_replay"].splitlines()[:6]:
                body.append(f"• {line}\n", style="white")
        else:
            body.append("• No evidence context yet\n", style="dim")

        body.append("\nTool timeline\n", style="bold cyan")
        if recent_events:
            for event in recent_events[-5:]:
                status = getattr(event, "status", "info")
                symbol = "●"
                color = "green" if status == "success" else ("red" if status == "error" else "yellow")
                title = getattr(event, "title", "event")
                detail = getattr(event, "detail", "")
                body.append(f"{symbol} {title}\n", style=color)
                if detail:
                    body.append(f"  {detail[:80]}\n", style="dim")
        else:
            body.append("• No events yet\n", style="dim")

        return Panel(body, title="Right Rail", border_style="magenta", box=box.ROUNDED)

    def _build_footer_panel(self, snapshot: dict[str, Any]) -> Panel:
        state = snapshot["state"]
        footer = Text()
        footer.append("Sếp > ", style="bold cyan")
        footer.append("type a message or / command", style="white on grey23")
        footer.append("\n")
        footer.append("Suggestions: ", style="bold #f0a27a")
        footer.append("  ".join(self._command_hints()), style="white")
        footer.append(f"\nmode={state.mode.value} | provider={snapshot['provider_label']} | Tab opens completions", style="dim")
        return Panel(footer, border_style="cyan", box=box.SQUARE)

    @staticmethod
    def _parse_mode(value: str) -> AgentMode:
        normalized = (value or "").strip().lower()
        for mode in AgentMode:
            if mode.value == normalized:
                return mode
        return AgentMode.CHAT
