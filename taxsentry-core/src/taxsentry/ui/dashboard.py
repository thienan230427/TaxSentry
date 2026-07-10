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
from .theme import ACCENT, BOX, BOX_SOFT, MUTED, PRIMARY, SECONDARY, SUCCESS, WARN, blue_panel, section_title, status_strip

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
            Layout(self._header_panel(snapshot), size=5),
            Layout(name="body", ratio=1),
            Layout(self._footer_panel(snapshot), size=4),
        )
        layout["body"].update(self._body_panel(snapshot))
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
        text.append("TaxSentry Ocean Dashboard\n", style=f"bold {PRIMARY}")
        text.append("Read-only status view.\n", style=f"dim {MUTED}")
        text.append("\n")
        text.append_text(
            status_strip(
                [
                    ("provider", "healthy" if ok else "degraded", f"bold {SUCCESS}" if ok else f"bold {WARN}"),
                    ("jobs", str(len(snapshot.recent_jobs)), f"bold {SECONDARY}"),
                    ("sessions", str(len(snapshot.recent_sessions)), f"bold {ACCENT}"),
                    ("reports", str(len(snapshot.recent_reports)), "white"),
                ],
            ),
        )
        text.append(f"\n{message}", style=f"dim {MUTED}" if ok else f"bold {WARN}")
        return blue_panel(text, title="Operational Snapshot", subtitle="Stacked layout", border_style=PRIMARY, box_style=BOX)

    def _body_panel(self, snapshot: DashboardSnapshot) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_row(section_title("Jobs", "Latest execution trail"))
        grid.add_row(self._jobs_table(snapshot))
        grid.add_row(section_title("Trace", "Replay"))
        grid.add_row(self._trace_block(snapshot))
        grid.add_row(section_title("Sessions", "Recent history"))
        grid.add_row(self._sessions_table(snapshot))
        return blue_panel(grid, border_style=PRIMARY, box_style=BOX_SOFT)

    def _jobs_table(self, snapshot: DashboardSnapshot) -> Table:
        table = Table(title="Recent Jobs", box=BOX, expand=True)
        table.add_column("Job", style=SECONDARY, no_wrap=True)
        table.add_column("State", style=SUCCESS)
        table.add_column("Type", style="white")
        table.add_column("Source", style=ACCENT)
        for job in snapshot.recent_jobs[:8]:
            table.add_row(
                str(job.job_id)[:10],
                str(job.state),
                str(job.job_type),
                str(job.source_file or "-"),
            )
        if not snapshot.recent_jobs:
            table.add_row("-", "empty", "-", "-")
        return table

    def _trace_block(self, snapshot: DashboardSnapshot) -> Text:
        body = Text()
        if snapshot.trace_replay:
            body.append(snapshot.trace_replay[:1200], style="white")
        else:
            body.append("No replay data available yet.\n", style=f"dim {MUTED}")

        body.append("\nRecent reports\n", style=f"bold {SECONDARY}")
        if snapshot.recent_reports:
            for report in snapshot.recent_reports[:3]:
                body.append(
                    f"• {report.get('file_name', 'n/a')} | {report.get('tax_risk_status', 'n/a')} | {report.get('status', 'n/a')}\n",
                    style="white",
                )
        else:
            body.append("• No reports yet\n", style=f"dim {MUTED}")
        return body

    def _sessions_table(self, snapshot: DashboardSnapshot) -> Table:
        table = Table(title="Recent Sessions", box=BOX, expand=True)
        table.add_column("Session", style=SECONDARY, no_wrap=True)
        table.add_column("Mode", style="white")
        table.add_column("Outcome", style=SUCCESS)
        table.add_column("Started", style=ACCENT)
        for session in snapshot.recent_sessions[:8]:
            table.add_row(
                str(session.get("session_id", "-"))[:10],
                str(session.get("mode", "-")),
                str(session.get("outcome") or "open"),
                str(session.get("started_at", "-"))[:19],
            )
        if not snapshot.recent_sessions:
            table.add_row("-", "empty", "-", "-")
        return table

    def _footer_panel(self, snapshot: DashboardSnapshot) -> Panel:
        footer = Text()
        footer.append("Refresh: Enter  |  q: exit", style=f"bold {PRIMARY}")
        footer.append(
            f"\nLatest event count: {len(snapshot.events)} | Replay available: {'yes' if snapshot.trace_replay else 'no'}",
            style=f"dim {MUTED}",
        )
        return blue_panel(footer, title="Live Footer", subtitle="Status", border_style=PRIMARY, box_style=BOX)

