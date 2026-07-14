from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import MEMORY_DB, ensure_directories

STATES = ("queued", "fetching", "extracting", "analyzing", "needs_review", "rendering", "delivering", "completed", "failed")
TRANSITIONS = {
    "queued": {"fetching", "failed"},
    "fetching": {"extracting", "failed"},
    "extracting": {"analyzing", "needs_review", "failed"},
    "analyzing": {"needs_review", "rendering", "failed"},
    "needs_review": {"failed"},
    "rendering": {"delivering", "failed"},
    "delivering": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
}
REQUEUEABLE = {"fetching", "extracting", "analyzing", "needs_review", "rendering", "delivering", "failed"}


class JobStore:
    def __init__(self, path: Path = MEMORY_DB):
        ensure_directories()
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, gmail_message_id TEXT NOT NULL UNIQUE, sender TEXT NOT NULL,
          subject TEXT NOT NULL DEFAULT '', state TEXT NOT NULL, retries INTEGER NOT NULL DEFAULT 0,
          error TEXT NOT NULL DEFAULT '', report_path TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS attachments (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, mime_type TEXT NOT NULL, UNIQUE(job_id, sha256));
        CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, job_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, confidence REAL NOT NULL, pdf_path TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, channel TEXT NOT NULL, external_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, provider TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, job_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS memory (id TEXT PRIMARY KEY, text TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        self.connection.commit()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_job(self, gmail_message_id: str, sender: str, subject: str = "") -> dict[str, Any] | None:
        job_id, now = str(uuid.uuid4()), self.now()
        try:
            self.connection.execute("INSERT INTO jobs VALUES (?, ?, ?, ?, 'queued', 0, '', '', ?, ?)", (job_id, gmail_message_id, sender, subject, now, now))
            self.connection.commit()
            return self.get(job_id)
        except sqlite3.IntegrityError:
            return None

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def by_message(self, message_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM jobs WHERE gmail_message_id = ?", (message_id,)).fetchone()
        return dict(row) if row else None

    def resolve(self, prefix: str = "") -> dict[str, Any] | None:
        if not prefix:
            rows = self.recent_jobs(1)
            return rows[0] if rows else None
        row = self.connection.execute("SELECT * FROM jobs WHERE id LIKE ? ORDER BY created_at DESC LIMIT 1", (f"{prefix}%",)).fetchone()
        return dict(row) if row else None

    def requeue(self, job_id: str, *, approved: bool = False) -> None:
        job = self.get(job_id)
        if not job or job["state"] not in REQUEUEABLE or (approved and job["state"] != "needs_review"):
            raise ValueError("Only interrupted, failed, or needs-review jobs can be requeued")
        self.connection.execute("UPDATE jobs SET state='queued', retries=0, error='', updated_at=? WHERE id=?", (self.now(), job_id))
        self.event(job_id, "approved" if approved else "retry_requested", {})
        self.connection.commit()

    def is_approved(self, job_id: str) -> bool:
        row = self.connection.execute("SELECT kind FROM events WHERE job_id=? AND kind IN ('approved', 'approval_consumed') ORDER BY created_at DESC LIMIT 1", (job_id,)).fetchone()
        return bool(row and row["kind"] == "approved")

    def consume_approval(self, job_id: str) -> None:
        self.event(job_id, "approval_consumed", {})
        self.connection.commit()

    def transition(self, job_id: str, state: str, *, error: str = "", report_path: str = "") -> None:
        if state not in STATES:
            raise ValueError(f"Unknown job state: {state}")
        current = self.get(job_id)
        if not current or state not in TRANSITIONS[current["state"]]:
            raise ValueError(f"Invalid job transition: {current['state'] if current else 'missing'} -> {state}")
        self.connection.execute("UPDATE jobs SET state=?, error=?, report_path=CASE WHEN ?='' THEN report_path ELSE ? END, updated_at=? WHERE id=?", (state, error, report_path, report_path, self.now(), job_id))
        self.event(job_id, "state", {"state": state, "error": error})
        self.connection.commit()

    def increment_retry(self, job_id: str, error: str) -> int:
        self.connection.execute("UPDATE jobs SET retries=retries+1, error=?, updated_at=? WHERE id=?", (error, self.now(), job_id))
        self.connection.commit()
        return int(self.get(job_id)["retries"])

    def attachment(self, job_id: str, *, name: str, path: str, sha256: str, mime_type: str) -> None:
        self.connection.execute("INSERT OR IGNORE INTO attachments VALUES (?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), job_id, name, path, sha256, mime_type))
        self.connection.commit()

    def report(self, job_id: str, payload: dict[str, Any], confidence: float, pdf_path: str = "") -> None:
        self.connection.execute("INSERT OR REPLACE INTO reports VALUES (?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), job_id, json.dumps(payload, ensure_ascii=False), confidence, pdf_path, self.now()))
        self.connection.commit()

    def delivery(self, job_id: str, channel: str, status: str, external_id: str = "") -> None:
        self.connection.execute("INSERT INTO deliveries VALUES (?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), job_id, channel, external_id, status, self.now()))
        self.connection.commit()

    def delivered(self, job_id: str, channel: str) -> bool:
        return self.connection.execute("SELECT 1 FROM deliveries WHERE job_id=? AND channel=? AND status='sent' LIMIT 1", (job_id, channel)).fetchone() is not None

    def event(self, job_id: str | None, kind: str, payload: dict[str, Any]) -> None:
        self.connection.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)", (str(uuid.uuid4()), job_id, kind, json.dumps(payload, ensure_ascii=False), self.now()))
        self.connection.commit()

    def recent_jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))]

    def latest_report(self) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT reports.*, jobs.subject, jobs.sender FROM reports JOIN jobs ON jobs.id=reports.job_id ORDER BY reports.created_at DESC LIMIT 1").fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def report_for_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT reports.*, jobs.subject, jobs.sender FROM reports JOIN jobs ON jobs.id=reports.job_id WHERE reports.job_id=?",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def job_events(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT kind, payload, created_at FROM events WHERE job_id=? ORDER BY created_at",
            (job_id,),
        ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def create_session(self, provider: str) -> str:
        session_id = str(uuid.uuid4())
        self.connection.execute("INSERT INTO sessions VALUES (?, ?, ?)", (session_id, provider, self.now()))
        self.connection.commit()
        return session_id

    def add_message(self, session_id: str, role: str, content: str) -> None:
        self.connection.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), session_id, role, content, self.now()),
        )
        self.connection.commit()

    def session_messages(self, session_id: str, limit: int = 24) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT role, content, created_at FROM messages WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def recent_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                "SELECT sessions.id, sessions.provider, sessions.created_at, "
                "COUNT(messages.id) AS message_count "
                "FROM sessions LEFT JOIN messages ON messages.session_id=sessions.id "
                "GROUP BY sessions.id ORDER BY sessions.created_at DESC LIMIT ?",
                (limit,),
            )
        ]

    def clear_session(self, session_id: str) -> None:
        self.connection.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
