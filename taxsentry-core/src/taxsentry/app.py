from __future__ import annotations

from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.table import Table

from .ui.hermes_shell import HermesShell
from .ui.dashboard import TaxSentryDashboard
from .config import describe_config, load_config
from .providers import from_settings, health_check
from .runtime.service import TaxSentryRuntimeService

console = Console()


def run_tui() -> int:
    shell = HermesShell()
    return shell.run()


def run_dashboard() -> int:
    dashboard = TaxSentryDashboard()
    return dashboard.run()


def run_status() -> int:
    service = TaxSentryRuntimeService()
    settings = service.settings
    provider = from_settings(settings)
    ok, message = health_check(provider)
    console.print(Panel(service.status_text(), title="TaxSentry status", border_style="green"))
    return 0 if ok else 1


def run_jobs(limit: int = 10) -> int:
    service = TaxSentryRuntimeService()
    jobs = service.recent_jobs(limit=limit)
    table = Table(title="Recent jobs")
    table.add_column("Job ID", style="cyan")
    table.add_column("Type", style="white")
    table.add_column("State", style="green")
    table.add_column("Source", style="magenta")
    table.add_column("Session", style="yellow")
    table.add_column("Retry", style="blue")
    if not jobs:
        console.print(Panel("No recent jobs yet.", title="Jobs", border_style="cyan"))
        return 0
    for job in jobs:
        table.add_row(
            job.job_id[:10],
            job.job_type,
            job.state,
            job.source_file or "-",
            (job.session_id or "-")[:10],
            str(job.retry_count),
        )
    console.print(table)
    return 0


def run_replay(session_id: str | None = None) -> int:
    service = TaxSentryRuntimeService()
    target_session = session_id
    if not target_session:
        recent_sessions = service.recent_sessions(limit=10)
        if not recent_sessions:
            console.print(Panel("No session found to replay.", title="Replay", border_style="red"))
            return 1

        table = Table(title="Recent sessions")
        table.add_column("#", style="cyan", no_wrap=True)
        table.add_column("Session", style="white")
        table.add_column("Mode", style="green")
        table.add_column("Outcome", style="magenta")
        table.add_column("Started", style="yellow")
        for index, session in enumerate(recent_sessions, start=1):
            table.add_row(
                str(index),
                str(session.get("session_id", "-"))[:12],
                str(session.get("mode", "-")),
                str(session.get("outcome") or "open"),
                str(session.get("started_at", "-"))[:19],
            )
        console.print(table)
        choice = Prompt.ask("Select session by number", default="1")
        try:
            selected_index = max(1, min(len(recent_sessions), int(choice))) - 1
        except Exception:
            selected_index = 0
        target_session = recent_sessions[selected_index]["session_id"]
    if not target_session:
        console.print(Panel("No session found to replay.", title="Replay", border_style="red"))
        return 1

    replay = service.replay_session(target_session)
    if not replay:
        console.print(Panel(f"No replay data available for {target_session}.", title="Replay", border_style="red"))
        return 1

    console.print(Panel(replay, title=f"Trace replay: {target_session}", border_style="cyan"))
    return 0


def run_memory_list() -> int:
    settings = load_config()
    memory = bootstrap_memory(settings)
    facts = memory.recent_facts(limit=20)
    table = Table(title="Memory facts")
    table.add_column("Kind")
    table.add_column("Text")
    table.add_column("Source")
    for fact in facts:
        table.add_row(fact["kind"], fact["text"], fact["source"])
    console.print(table)
    return 0


def run_memory_add(text: str) -> int:
    settings = load_config()
    memory = bootstrap_memory(settings)
    memory.remember_fact(text, source="cli")
    console.print(Panel(f"Saved memory: {text}", border_style="green"))
    return 0


def run_doctor() -> int:
    service = TaxSentryRuntimeService()
    settings = service.settings
    provider = from_settings(settings)
    ok, message = health_check(provider)
    console.print(Panel("Doctor report", border_style="cyan"))
    console.print(describe_config(settings))
    console.print(f"Provider health: {'OK' if ok else 'FAIL'} — {message}")
    console.print(f"Recent jobs: {len(service.recent_jobs(limit=5))}")
    return 0 if ok else 1
