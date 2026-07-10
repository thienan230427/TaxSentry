from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from .theme import ACCENT, BOX, BOX_SOFT, MUTED, PRIMARY, SECONDARY, SUCCESS, WARN, blue_panel, section_title, status_strip

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.output import DummyOutput
    from prompt_toolkit.shortcuts import CompleteStyle
except Exception:  # pragma: no cover - graceful fallback if dependency is missing
    PromptSession = None
    AutoSuggestFromHistory = None
    WordCompleter = None
    HTML = None
    DummyOutput = None
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
    body: Panel
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
        kwargs = {
            "completer": completer,
            "auto_suggest": AutoSuggestFromHistory(),
            "complete_while_typing": True,
            "enable_history_search": True,
            "complete_style": CompleteStyle.MULTI_COLUMN,
            "reserve_space_for_menu": 8,
        }
        if self._should_use_dummy_prompt_output() and DummyOutput is not None:
            kwargs["output"] = DummyOutput()

        try:
            return PromptSession(**kwargs)
        except Exception as exc:
            if DummyOutput is None or not self._is_prompt_console_error(exc):
                raise
            kwargs["output"] = DummyOutput()
            return PromptSession(**kwargs)

    @staticmethod
    def _should_use_dummy_prompt_output() -> bool:
        return os.getenv("CI", "").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _is_prompt_console_error(exc: Exception) -> bool:
        return exc.__class__.__name__ == "NoConsoleScreenBufferError"

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
            Layout(name="main", ratio=1),
            Layout(frame.footer, size=4),
        )
        layout["main"].update(frame.body)
        console.print(layout)

    def _build_frame(self, *, last_result: str, initial: bool) -> HermesFrame:
        snapshot = self.kernel.snapshot()
        header = self._build_header_panel(snapshot)
        body = self._build_center_panel(snapshot, last_result=last_result, initial=initial)
        footer = self._build_footer_panel(snapshot)
        return HermesFrame(header=header, body=body, footer=footer)

    def _build_provider_picker_panel(self, presets: list[ProviderPreset]) -> Panel:
        table = Table.grid(expand=True)
        table.add_column()
        header = Text()
        header.append("Select provider:\n", style=f"bold {PRIMARY}")
        header.append("Select by number, Enter to confirm.\n\n", style=f"dim {MUTED}")
        for index, preset in enumerate(presets, start=1):
            active = preset.key == self.kernel.state.provider_key
            marker = "(o)" if not active else "(•)"
            color = SUCCESS if active else ("white" if preset.available else WARN)
            badge = f" <{preset.badge}>" if preset.badge else ""
            availability = "" if preset.available else " [unavailable]"
            header.append(f"{marker} {index}. {preset.label}{badge} ({preset.description}){availability}\n", style=color)
        table.add_row(header)
        return blue_panel(table, title="Provider Select", subtitle="Routing", border_style=PRIMARY, box_style=BOX)

    def _build_header_panel(self, snapshot: dict[str, Any]) -> Panel:
        provider = snapshot["provider"]
        provider_health = snapshot["provider_health"]
        state = snapshot["state"]
        title = Text()
        title.append("TaxSentry", style=f"bold {PRIMARY}")
        title.append("  ")
        title.append(
            f"{get_value(self.settings, 'agent.name', 'TaxSentry')}",
            style=f"bold {SECONDARY}",
        )
        title.append("\n")
        title.append_text(
            status_strip(
                [
                    ("mode", state.mode.value, f"bold {ACCENT}"),
                    ("provider", snapshot["provider_label"], f"bold {SECONDARY}"),
                    ("health", "OK" if provider_health[0] else "FAIL", f"bold {SUCCESS}" if provider_health[0] else f"bold {WARN}"),
                ],
            ),
        )
        return blue_panel(title, border_style=PRIMARY, box_style=BOX, padding=(0, 2))

    def _build_left_rail(self, snapshot: dict[str, Any]) -> Panel:
        presets = self.kernel.available_provider_presets()
        table = Table.grid(expand=True)
        table.add_column()

        provider_block = Text()
        provider_block.append("Mission Deck\n", style=f"bold {PRIMARY}")
        provider_block.append("Providers\n", style=f"bold {SECONDARY}")
        for index, preset in enumerate(presets, start=1):
            active = preset.key == self.kernel.state.provider_key
            marker = "▶" if active else "•"
            color = SUCCESS if active else ("white" if preset.available else WARN)
            provider_block.append(f"{marker} {index}. {preset.label}\n", style=color)
            provider_block.append(f"    {preset.description}\n", style=f"dim {MUTED}")

        actions = Text()
        actions.append("\nActions\n", style=f"bold {SECONDARY}")
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
        sessions.append("\nRecent sessions\n", style=f"bold {SECONDARY}")
        session = snapshot["session"]
        sessions.append(f"• Current: {session.session_id[:8]} ({session.mode})\n", style="white")
        sessions.append(f"• Started: {session.started_at}\n", style=f"dim {MUTED}")
        sessions.append(f"• Turns: {len(session.messages)}\n", style=f"dim {MUTED}")

        table.add_row(provider_block)
        table.add_row(actions)
        table.add_row(sessions)
        return blue_panel(table, title="Left Rail", subtitle="Providers and quick actions", border_style=PRIMARY, box_style=BOX)

    def _build_center_panel(self, snapshot: dict[str, Any], *, last_result: str, initial: bool) -> Panel:
        state = snapshot["state"]
        active_plan = snapshot.get("active_plan") or "No active plan"
        body = Text()
        body.append("Chat\n", style=f"bold {PRIMARY}")
        body.append(f"gateway connected | {self._last_frame_note}\n", style=f"dim {MUTED}")
        body.append(f"plan={active_plan} | progress={state.last_progress or '-'}\n\n", style=f"dim {MUTED}")

        if initial:
            body.append("Ready.\n", style="white")
        elif last_result:
            if state.last_user_input:
                body.append("Sếp\n", style=f"bold {SECONDARY}")
                body.append(f" {state.last_user_input} \n\n", style="white on grey19")
            body.append("TaxSentry\n", style=f"bold {PRIMARY}")
            body.append(last_result[:1200], style="white")
        else:
            body.append("Waiting.\n", style=f"dim {MUTED}")

        return blue_panel(body, title="Chat", subtitle="Live stream", border_style=PRIMARY, box_style=BOX_SOFT)

    def _build_footer_panel(self, snapshot: dict[str, Any]) -> Panel:
        state = snapshot["state"]
        footer = Text()
        footer.append("Sếp > type a message or / command", style=f"bold {SECONDARY}")
        footer.append(f"\nmode={state.mode.value} | provider={snapshot['provider_label']}", style=f"dim {MUTED}")
        return blue_panel(footer, border_style=PRIMARY, box_style=BOX_SOFT)

    @staticmethod
    def _parse_mode(value: str) -> AgentMode:
        normalized = (value or "").strip().lower()
        for mode in AgentMode:
            if mode.value == normalized:
                return mode
        return AgentMode.CHAT
