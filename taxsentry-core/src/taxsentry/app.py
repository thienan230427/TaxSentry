from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import describe_config, get_value, load_config
from .memory import MemoryStore, bootstrap_memory
from .providers import ProviderConfig, ProviderError, from_settings, generate_chat, health_check, provider_label

console = Console()


@dataclass
class AgentSession:
    settings: dict[str, Any]
    memory: MemoryStore
    provider: ProviderConfig
    session_id: str

    @property
    def agent_name(self) -> str:
        return str(get_value(self.settings, "agent.name", "TaxSentry"))

    def memory_context(self) -> str:
        return self.memory.build_context(
            self.session_id,
            fact_limit=int(get_value(self.settings, "memory.max_facts", 6)),
            turn_limit=int(get_value(self.settings, "memory.max_turns", 8)),
        )

    def system_prompt(self) -> str:
        persona = str(get_value(self.settings, "agent.persona", "practical"))
        language = str(get_value(self.settings, "agent.language", "vi"))
        memory_context = self.memory_context()
        base = [
            f"You are {self.agent_name}, a local-first AI agent.",
            f"Persona: {persona}.",
            f"Respond in {language}; if the user writes Vietnamese, answer naturally in Vietnamese.",
            "Be concise, helpful, and explicit when data is missing.",
            "When you learn a durable preference or identity fact, suggest /remember so it can be persisted.",
            "You may help with finance, tax, setup, coding, and general agent tasks.",
        ]
        if memory_context:
            base.append("\nMemory context:\n" + memory_context)
        return "\n".join(base)

    def reply(self, user_text: str) -> str:
        self.memory.append_turn(self.session_id, "user", user_text)
        messages = [{"role": "system", "content": self.system_prompt()}]
        recent_turns = self.memory.recent_turns(self.session_id, limit=8)
        for turn in recent_turns:
            messages.append({"role": turn["role"], "content": turn["content"]})
        response = generate_chat(self.provider, messages)
        self.memory.append_turn(self.session_id, "assistant", response)
        return response


def build_session() -> AgentSession:
    settings = load_config()
    memory = bootstrap_memory(settings)
    provider = from_settings(settings)
    session_id = memory.start_session(str(get_value(settings, "memory.session_title", "TaxSentry session")))
    return AgentSession(settings=settings, memory=memory, provider=provider, session_id=session_id)


def render_welcome(settings: dict[str, Any]) -> None:
    provider = from_settings(settings)
    top = Table.grid(expand=True)
    top.add_column(ratio=1)
    top.add_column(ratio=1)
    top.add_row(
        Text(f"{get_value(settings, 'agent.name', 'TaxSentry')}", style="bold bright_cyan"),
        Text(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), style="dim"),
    )
    console.print(Panel(top, title="TaxSentry Agent", border_style="bright_cyan"))

    left = Table.grid(expand=True)
    left.add_column()
    left.add_row(f"Provider: [bold]{provider_label(provider)}[/bold]")
    left.add_row(f"Model: [bold]{provider.model}[/bold]")
    left.add_row(f"Endpoint: [dim]{provider.base_url}[/dim]")

    memory = Table.grid(expand=True)
    memory.add_column()
    memory.add_row(f"Memory: [bold]{'on' if get_value(settings, 'agent.memory_enabled', True) else 'off'}[/bold]")
    memory.add_row(f"Facts limit: [bold]{get_value(settings, 'memory.max_facts', 50)}[/bold]")
    memory.add_row(f"Turns limit: [bold]{get_value(settings, 'memory.max_turns', 12)}[/bold]")

    console.print(Panel.fit(left, title="Runtime", border_style="cyan"))
    console.print(Panel.fit(memory, title="Memory", border_style="magenta"))
    console.print(Panel.fit(describe_config(settings), title="Configured state", border_style="green"))


def run_tui() -> int:
    settings = load_config()
    render_welcome(settings)
    session = build_session()
    console.print(Panel("Type /help for commands, /exit to quit, /remember to save a durable memory.", border_style="yellow"))

    while True:
        try:
            user_text = input("\nSếp > ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nExiting...")
            return 0

        if not user_text:
            continue
        if user_text in {"/exit", "/quit", "/q"}:
            console.print("Goodbye ✨")
            return 0
        if user_text in {"/help", "help"}:
            console.print("Commands: /help, /status, /memory, /remember <text>, /exit")
            continue
        if user_text == "/status":
            console.print(Panel(describe_config(load_config()), title="Status", border_style="blue"))
            continue
        if user_text == "/memory":
            facts = session.memory.recent_facts(limit=10)
            table = Table(title="Recent memory facts")
            table.add_column("Kind")
            table.add_column("Text")
            table.add_column("Source")
            for fact in facts:
                table.add_row(fact["kind"], fact["text"], fact["source"])
            console.print(table)
            continue
        if user_text.startswith("/remember "):
            fact = user_text[len("/remember "):].strip()
            session.memory.remember_fact(fact, source="manual")
            console.print(Panel(f"Saved memory: {fact}", border_style="green"))
            continue

        try:
            reply = session.reply(user_text)
        except ProviderError as exc:
            console.print(Panel(str(exc), title="Provider error", border_style="red"))
            continue
        except Exception as exc:
            console.print(Panel(str(exc), title="Agent error", border_style="red"))
            continue

        console.print(Panel(reply, title=f"{get_value(session.settings, 'agent.name', 'TaxSentry')}", border_style="bright_blue"))


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
