from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import MEMORY_DB, ensure_directories, get_value, save_config


@dataclass
class MemorySnapshot:
    facts: list[dict[str, Any]]
    turns: list[dict[str, Any]]
    session_id: str | None


class MemoryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        ensure_directories()
        self.db_path = db_path or MEMORY_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profile (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                """
            )

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def upsert_profile(self, settings: dict[str, Any]) -> None:
        payload = {
            "agent_name": get_value(settings, "agent.name", "TaxSentry"),
            "persona": get_value(settings, "agent.persona", "practical"),
            "provider": json.dumps(get_value(settings, "provider", {}), ensure_ascii=False),
        }
        with self._connect() as conn:
            for key, value in payload.items():
                conn.execute(
                    "INSERT INTO profile(key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, value, self._now()),
                )

    def remember_fact(self, text: str, kind: str = "preference", source: str = "setup") -> None:
        text = text.strip()
        if not text:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO facts(kind, text, source, created_at) VALUES (?, ?, ?, ?)",
                (kind, text, source, self._now()),
            )

    def recent_facts(self, limit: int = 6) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, text, source, created_at FROM facts ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_facts(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        needle = f"%{query.strip()}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, text, source, created_at FROM facts WHERE text LIKE ? ORDER BY id DESC LIMIT ?",
                (needle, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def start_session(self, title: str) -> str:
        session_id = uuid.uuid4().hex[:12]
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions(session_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (session_id, title, now, now),
            )
        return session_id

    def touch_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (self._now(), session_id))

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO turns(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, self._now()),
            )
            conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (self._now(), session_id))

    def recent_turns(self, session_id: str, limit: int = 8) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM turns WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def build_context(self, session_id: str | None, fact_limit: int = 6, turn_limit: int = 8) -> str:
        facts = self.recent_facts(limit=fact_limit)
        turns: list[dict[str, Any]] = []
        if session_id:
            turns = self.recent_turns(session_id, limit=turn_limit)
        sections: list[str] = []
        if facts:
            sections.append("Recent memory facts:\n" + "\n".join(f"- {item['text']}" for item in facts))
        if turns:
            sections.append(
                "Recent conversation:\n"
                + "\n".join(f"- {item['role']}: {item['content']}" for item in turns)
            )
        return "\n\n".join(sections).strip()

    def snapshot(self, session_id: str | None = None) -> MemorySnapshot:
        return MemorySnapshot(
            facts=self.recent_facts(),
            turns=self.recent_turns(session_id) if session_id else [],
            session_id=session_id,
        )


def bootstrap_memory(config: dict[str, Any]) -> MemoryStore:
    store = MemoryStore()
    store.upsert_profile(config)
    return store


