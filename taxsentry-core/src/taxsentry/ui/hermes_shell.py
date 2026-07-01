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

from taxsentry.agent import AgentKernel, AgentMode, ProviderPreset
from taxsentry.config import describe_config, get_value, load_config
from taxsentry.database.db_manager import TaxSentryDBManager

console = Console()


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

    def run(self) -> int:
        self._show_provider_picker()
        self._sync_kernel_provider()
        self._render_screen(initial=True)

        while True:
            try:
                user_text = input("\nSếp > ").strip()
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

            result = self.kernel.handle(user_text, progress_callback=self._on_progress)
            self._last_turn = result
            self._last_frame_note = result.route
            self._render_screen(last_result=result.response.text)

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
            Layout(frame.header, size=7),
            Layout(name="body", ratio=1),
            Layout(frame.footer, size=4),
        )
        layout["body"].split_row(
            Layout(frame.left, ratio=3),
            Layout(frame.center, ratio=5),
            Layout(frame.right, ratio=4),
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
        active_plan = snapshot.get("active_plan") or "-"
        title = Text()
        title.append("TaxSentry 1.1.2\n", style="bold white")
        title.append(
            f"Agent: {get_value(self.settings, 'agent.name', 'TaxSentry')}  ",
            style="cyan",
        )
        title.append(f"Mode: {state.mode.value}  ", style="magenta")
        title.append(f"Provider: {snapshot['provider_label']}  ", style="green")
        title.append(f"Model: {provider.model}  ", style="yellow")
        title.append(f"Session: {state.session_id[:8]}  ", style="white")
        title.append(f"Health: {'OK' if provider_health[0] else 'FAIL'}", style="bold green" if provider_health[0] else "bold red")
        title.append(f"\nPlan: {active_plan[:80]}", style="dim")
        return Panel(title, border_style="deep_sky_blue1", style="bold white on black")

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
        body.append("Main Task Stream\n", style="bold yellow")
        body.append(f"Current frame note: {self._last_frame_note}\n", style="dim")
        body.append(f"Last route: {state.last_route}\n", style="white")
        body.append(f"Last tool: {state.last_tool_name or '-'} ({state.last_tool_status or '-'})\n", style="white")
        body.append(f"Last plan: {active_plan}\n", style="white")
        body.append(f"Progress: {state.last_progress or '-'}\n", style="cyan")
        body.append(f"Toolchain: {', '.join(toolchain) if toolchain else '-'}\n", style="dim")
        if turn_plan:
            body.append(f"Turn plan: {turn_plan}\n", style="dim")
        if turn_toolchain:
            body.append(f"Turn tools: {', '.join(turn_toolchain)}\n", style="dim")
        body.append(f"Last input: {state.last_user_input or '-'}\n\n", style="white")

        if initial:
            body.append("Type a request or use /help for shortcuts.\n", style="green")
            body.append("Try /mode analysis for audit flow or /provider to switch model.\n", style="cyan")
        elif last_result:
            body.append("Latest response:\n", style="bold green")
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

        return Panel(body, title="Conversation / Task Stream", border_style="green", box=box.ROUNDED)

    def _build_right_rail(self, snapshot: dict[str, Any]) -> Panel:
        memory_facts = snapshot["memory_facts"]
        recent_reports = snapshot["recent_reports"]
        evidence_context = snapshot["evidence_context"]
        recent_events = snapshot.get("recent_events") or []

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

        body.append("\nTrace preview\n", style="bold cyan")
        if evidence_context:
            body.append(f"• {evidence_context.get('source_file', 'n/a')}\n", style="white")
            body.append(f"• session={evidence_context.get('session_id', 'n/a')}\n", style="dim")
            body.append(f"• trace={evidence_context.get('trace_id', 'n/a')}\n", style="dim")
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
        footer.append("Shortcuts: ", style="bold yellow")
        footer.append("/help  /status  /memory  /provider  /mode <name>  /audit  /tools  /trace  /exit", style="white")
        footer.append(f"\nStatus: mode={state.mode.value} | provider={snapshot['provider_label']} | session={state.session_id[:8]}", style="dim")
        return Panel(footer, border_style="deep_sky_blue1", box=box.ROUNDED)

    @staticmethod
    def _parse_mode(value: str) -> AgentMode:
        normalized = (value or "").strip().lower()
        for mode in AgentMode:
            if mode.value == normalized:
                return mode
        return AgentMode.CHAT
