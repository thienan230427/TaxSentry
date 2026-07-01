from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .ui.hermes_shell import HermesShell
from .config import describe_config, load_config
from .memory import bootstrap_memory
from .providers import from_settings, health_check

console = Console()


def run_tui() -> int:
    shell = HermesShell()
    return shell.run()


def run_status() -> int:
    settings = load_config()
    session_memory = bootstrap_memory(settings)
    provider = from_settings(settings)
    ok, message = health_check(provider)
    console.print(Panel(describe_config(settings), title="TaxSentry status", border_style="green"))
    console.print(f"Provider check: {'OK' if ok else 'FAIL'} — {message}")
    console.print(f"Memory DB: {session_memory.db_path}")
    return 0 if ok else 1


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
    settings = load_config()
    provider = from_settings(settings)
    ok, message = health_check(provider)
    console.print(Panel("Doctor report", border_style="cyan"))
    console.print(describe_config(settings))
    console.print(f"Provider health: {'OK' if ok else 'FAIL'} — {message}")
    return 0 if ok else 1
