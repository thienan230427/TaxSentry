from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from taxsentry.runtime.service import TaxSentryRuntimeService

console = Console()


@dataclass
class DashboardSnapshot:
    provider_health: tuple[bool, str]
    recent_jobs: list[Any]
    recent_sessions: list[dict[str, Any]]
    recent_reports: list[dict[str, Any]]
    events: list[dict[str, Any]]
    trace_replay: str


class TaxSentryDashboard:
    """Read-only operational dashboard for jobs, sessions, and traces."""

    def __init__(self, service: TaxSentryRuntimeService | None = None):
        self.service = service or TaxSentryRuntimeService()

    def run(self) -> int:
        while True:
            self._render()
            try:
                choice = input("\nEnter để refresh, q để thoát: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return 0
            if choice in {"q", "quit", "exit"}:
                return 0

    def _render(self) -> None:
        snapshot = self._snapshot()
        console.clear()
        layout = Layout()
        layout.split_column(
            Layout(self._header_panel(snapshot), size=7),
            Layout(name="body", ratio=1),
            Layout(self._footer_panel(snapshot), size=4),
        )
        layout["body"].split_row(
            Layout(self._jobs_panel(snapshot), ratio=4),
            Layout(self._center_panel(snapshot), ratio=5),
            Layout(self._sessions_panel(snapshot), ratio=4),
        )
        console.print(layout)

    def _snapshot(self) -> DashboardSnapshot:
        raw = self.service.snapshot(limit=5)
        return DashboardSnapshot(
            provider_health=raw["provider_health"],
            recent_jobs=raw["recent_jobs"],
            recent_sessions=raw["recent_sessions"],
            recent_reports=raw["recent_reports"],
            events=raw["events"],
            trace_replay=raw["trace_replay"],
        )

    def _header_panel(self, snapshot: DashboardSnapshot) -> Panel:
        ok, message = snapshot.provider_health
        text = Text()
        text.append("TaxSentry Dashboard\n", style="bold white")
        text.append(
            f"Provider health: {'OK' if ok else 'FAIL'} — {message}\n",
            style="green" if ok else "red",
        )
        text.append(
            f"Recent jobs: {len(snapshot.recent_jobs)} | Recent sessions: {len(snapshot.recent_sessions)} | Recent reports: {len(snapshot.recent_reports)}",
            style="cyan",
        )
        return Panel(text, border_style="deep_sky_blue1", style="bold white on black")

    def _jobs_panel(self, snapshot: DashboardSnapshot) -> Panel:
        table = Table(title="Recent Jobs", box=box.ROUNDED, expand=True)
        table.add_column("Job", style="cyan", no_wrap=True)
        table.add_column("State", style="green")
        table.add_column("Type", style="white")
        table.add_column("Source", style="magenta")
        for job in snapshot.recent_jobs[:8]:
            table.add_row(
                str(job.job_id)[:10],
                str(job.state),
                str(job.job_type),
                str(job.source_file or "-"),
            )
        if not snapshot.recent_jobs:
            table.add_row("-", "empty", "-", "-")
        return Panel(table, border_style="cyan", title="Jobs")

    def _center_panel(self, snapshot: DashboardSnapshot) -> Panel:
        body = Text()
        body.append("Trace / Replay\n", style="bold yellow")
        if snapshot.trace_replay:
            body.append(snapshot.trace_replay[:2500], style="white")
        else:
            body.append("No replay data available yet.\n", style="dim")

        body.append("\n\nRecent reports\n", style="bold cyan")
        if snapshot.recent_reports:
            for report in snapshot.recent_reports[:4]:
                body.append(
                    f"• {report.get('file_name', 'n/a')} | {report.get('tax_risk_status', 'n/a')} | {report.get('status', 'n/a')}\n",
                    style="white",
                )
        else:
            body.append("• No reports yet\n", style="dim")

        return Panel(body, title="Trace Center", border_style="green", box=box.ROUNDED)

    def _sessions_panel(self, snapshot: DashboardSnapshot) -> Panel:
        table = Table(title="Recent Sessions", box=box.ROUNDED, expand=True)
        table.add_column("Session", style="cyan", no_wrap=True)
        table.add_column("Mode", style="white")
        table.add_column("Outcome", style="green")
        table.add_column("Started", style="magenta")
        for session in snapshot.recent_sessions[:8]:
            table.add_row(
                str(session.get("session_id", "-"))[:10],
                str(session.get("mode", "-")),
                str(session.get("outcome") or "open"),
                str(session.get("started_at", "-"))[:19],
            )
        if not snapshot.recent_sessions:
            table.add_row("-", "empty", "-", "-")
        return Panel(table, border_style="magenta", title="Sessions")

    def _footer_panel(self, snapshot: DashboardSnapshot) -> Panel:
        footer = Text()
        footer.append("Refresh: Enter  |  Exit: q", style="bold yellow")
        footer.append(
            f"\nLatest event count: {len(snapshot.events)} | Replay available: {'yes' if snapshot.trace_replay else 'no'}",
            style="dim",
        )
        return Panel(footer, border_style="deep_sky_blue1", box=box.ROUNDED)

