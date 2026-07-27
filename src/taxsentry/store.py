from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import MEMORY_DB, ensure_directories

STATES = ("queued", "fetching", "extracting", "analyzing", "needs_review", "rendering", "delivering", "completed", "failed", "cancelled")
TRANSITIONS = {
    "queued": {"fetching", "failed", "cancelled"},
    "fetching": {"extracting", "failed", "cancelled"},
    "extracting": {"analyzing", "needs_review", "failed", "cancelled"},
    "analyzing": {"needs_review", "rendering", "failed", "cancelled"},
    "needs_review": {"delivering", "failed", "cancelled"},
    "rendering": {"needs_review", "delivering", "failed", "cancelled"},
    "delivering": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}
REQUEUEABLE = {"fetching", "extracting", "analyzing", "needs_review", "rendering", "delivering", "failed", "cancelled"}


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
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY, provider TEXT NOT NULL, platform TEXT NOT NULL DEFAULT 'terminal',
          company_id TEXT NOT NULL DEFAULT 'default', model TEXT NOT NULL DEFAULT '',
          system_prompt TEXT NOT NULL DEFAULT '', system_prompt_hash TEXT NOT NULL DEFAULT '',
          summary TEXT NOT NULL DEFAULT '', provider_thread_id TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, session_id TEXT NOT NULL, company_id TEXT NOT NULL DEFAULT 'default',
          role TEXT NOT NULL, content TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'terminal',
          trusted INTEGER NOT NULL DEFAULT 1, pinned INTEGER NOT NULL DEFAULT 0,
          expires_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, job_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS memory (id TEXT PRIMARY KEY, text TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS memory_items (
          id TEXT PRIMARY KEY, company_id TEXT NOT NULL, kind TEXT NOT NULL,
          content TEXT NOT NULL, provenance TEXT NOT NULL, sensitivity TEXT NOT NULL,
          effective_date TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1,
          trusted INTEGER NOT NULL DEFAULT 1, pinned INTEGER NOT NULL DEFAULT 0,
          expires_at TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_tombstones (
          id TEXT PRIMARY KEY, memory_id TEXT NOT NULL UNIQUE, company_id TEXT NOT NULL,
          content_hash TEXT NOT NULL, reason TEXT NOT NULL, deleted_at TEXT NOT NULL
        );
        """)
        self._ensure_column("sessions", "platform", "TEXT NOT NULL DEFAULT 'terminal'")
        self._ensure_column("sessions", "company_id", "TEXT NOT NULL DEFAULT 'default'")
        self._ensure_column("sessions", "model", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("sessions", "system_prompt", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("sessions", "system_prompt_hash", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("sessions", "summary", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("sessions", "provider_thread_id", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("sessions", "updated_at", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("messages", "company_id", "TEXT NOT NULL DEFAULT 'default'")
        self._ensure_column("messages", "source", "TEXT NOT NULL DEFAULT 'terminal'")
        self._ensure_column("messages", "trusted", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("messages", "pinned", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("messages", "expires_at", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("jobs", "company_id", "TEXT NOT NULL DEFAULT 'default'")
        self.connection.execute("UPDATE sessions SET updated_at=created_at WHERE updated_at=''")
        self.connection.execute(
            "INSERT OR IGNORE INTO memory_items "
            "(id, company_id, kind, content, provenance, sensitivity, effective_date, revision, "
            "trusted, pinned, expires_at, created_at, updated_at) "
            "SELECT id, 'default', 'legacy', text, 'sqlite:memory', 'internal', "
            "substr(created_at, 1, 10), 1, 1, 1, '', created_at, created_at FROM memory"
        )
        self.connection.executescript("""
        CREATE INDEX IF NOT EXISTS idx_sessions_company_updated ON sessions(company_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_messages_company_created ON messages(company_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_memory_company_updated ON memory_items(company_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_company_created ON jobs(company_id, created_at);
        """)
        self.connection.commit()

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _job_message_key(message_id: str, company_id: str) -> str:
        # ponytail: preserve the v2 UNIQUE column; rebuild jobs if raw cross-company
        # message IDs must become directly queryable.
        return (
            message_id
            if company_id == "default"
            else "v3:" + json.dumps([company_id, message_id], separators=(",", ":"))
        )

    def create_job(
        self,
        gmail_message_id: str,
        sender: str,
        subject: str = "",
        *,
        company_id: str = "default",
    ) -> dict[str, Any] | None:
        job_id, now = str(uuid.uuid4()), self.now()
        try:
            self.connection.execute(
                """
                INSERT INTO jobs
                    (id, gmail_message_id, sender, subject, state, retries,
                     error, report_path, created_at, updated_at, company_id)
                VALUES (?, ?, ?, ?, 'queued', 0, '', '', ?, ?, ?)
                """,
                (
                    job_id,
                    self._job_message_key(gmail_message_id, company_id),
                    sender,
                    subject,
                    now,
                    now,
                    company_id,
                ),
            )
            self.connection.commit()
            return self.get(job_id)
        except sqlite3.IntegrityError:
            return None

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def by_message(
        self,
        message_id: str,
        *,
        company_id: str | None = None,
    ) -> dict[str, Any] | None:
        query = "SELECT * FROM jobs WHERE gmail_message_id = ?"
        params: tuple[Any, ...] = (
            self._job_message_key(message_id, company_id)
            if company_id is not None
            else message_id,
        )
        if company_id is not None:
            query += " AND company_id = ?"
            params += (company_id,)
        row = self.connection.execute(query, params).fetchone()
        return dict(row) if row else None

    def resolve(
        self,
        prefix: str = "",
        *,
        company_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not prefix:
            rows = self.recent_jobs(1, company_id=company_id)
            return rows[0] if rows else None
        query = "SELECT * FROM jobs WHERE id LIKE ?"
        params: tuple[Any, ...] = (f"{prefix}%",)
        if company_id is not None:
            query += " AND company_id=?"
            params += (company_id,)
        query += " ORDER BY created_at DESC LIMIT 1"
        row = self.connection.execute(query, params).fetchone()
        return dict(row) if row else None

    def requeue(self, job_id: str, *, approved: bool = False, reset_retries: bool = True) -> None:
        job = self.get(job_id)
        if not job or job["state"] not in REQUEUEABLE or (approved and job["state"] != "needs_review"):
            raise ValueError("Only interrupted, failed, or needs-review jobs can be requeued")
        retries = 0 if reset_retries else int(job["retries"])
        error = "" if reset_retries else str(job["error"])
        self.connection.execute("UPDATE jobs SET state='queued', retries=?, error=?, updated_at=? WHERE id=?", (retries, error, self.now(), job_id))
        kind = "approved" if approved else "retry_requested" if reset_retries else "retry_scheduled"
        self.event(job_id, kind, {"retries": retries})
        self.connection.commit()

    def request_cancel(self, job_id: str) -> None:
        job = self.get(job_id)
        if not job or job["state"] in {"completed", "failed", "cancelled"}:
            raise ValueError("Only active jobs can be cancelled")
        self.event(job_id, "cancel_requested", {})

    def cancel_requested(self, job_id: str) -> bool:
        row = self.connection.execute("SELECT kind FROM events WHERE job_id=? AND kind IN ('cancel_requested', 'cancelled') ORDER BY created_at DESC LIMIT 1", (job_id,)).fetchone()
        return bool(row and row["kind"] == "cancel_requested")

    def is_approved(self, job_id: str) -> bool:
        row = self.connection.execute("SELECT kind FROM events WHERE job_id=? AND kind IN ('approved', 'approval_consumed') ORDER BY created_at DESC LIMIT 1", (job_id,)).fetchone()
        return bool(row and row["kind"] == "approved")

    def consume_approval(self, job_id: str) -> None:
        self.event(job_id, "approval_consumed", {})
        self.connection.commit()

    def approve(self, job_id: str) -> None:
        job = self.get(job_id)
        if not job or job["state"] != "needs_review":
            raise ValueError("Only needs-review jobs can be approved")
        self.event(job_id, "approved", {})
        self.transition(job_id, "delivering", report_path=job.get("report_path", ""))

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

    def recent_jobs(
        self,
        limit: int = 10,
        *,
        company_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if company_id is None:
            rows = self.connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM jobs
                WHERE company_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (company_id, limit),
            )
        return [dict(row) for row in rows]

    def state_counts(self, *, company_id: str | None = None) -> dict[str, int]:
        counts = {state: 0 for state in STATES}
        if company_id is None:
            rows = self.connection.execute(
                "SELECT state, COUNT(*) total FROM jobs GROUP BY state"
            )
        else:
            rows = self.connection.execute(
                """
                SELECT state, COUNT(*) total FROM jobs
                WHERE company_id=?
                GROUP BY state
                """,
                (company_id,),
            )
        counts.update({row["state"]: int(row["total"]) for row in rows})
        return counts

    def latest_report(
        self,
        *,
        company_id: str | None = None,
    ) -> dict[str, Any] | None:
        query = (
            "SELECT reports.*, jobs.subject, jobs.sender, jobs.company_id "
            "FROM reports JOIN jobs ON jobs.id=reports.job_id"
        )
        params: tuple[Any, ...] = ()
        if company_id is not None:
            query += " WHERE jobs.company_id=?"
            params = (company_id,)
        query += " ORDER BY reports.created_at DESC LIMIT 1"
        row = self.connection.execute(query, params).fetchone()
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

    def create_session(
        self,
        provider: str,
        *,
        platform: str = "terminal",
        company_id: str = "default",
        model: str = "",
        system_prompt: str = "",
        system_prompt_hash: str = "",
    ) -> str:
        session_id, now = str(uuid.uuid4()), self.now()
        self.connection.execute(
            "INSERT INTO sessions "
            "(id, provider, platform, company_id, model, system_prompt, system_prompt_hash, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                provider,
                platform,
                company_id,
                model,
                system_prompt,
                system_prompt_hash,
                now,
                now,
            ),
        )
        self.connection.commit()
        return session_id

    def session(self, session_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def update_session_prompt(self, session_id: str, prompt: str, prompt_digest: str) -> None:
        self.connection.execute(
            "UPDATE sessions SET system_prompt=?, system_prompt_hash=?, updated_at=? WHERE id=?",
            (prompt, prompt_digest, self.now(), session_id),
        )
        self.connection.commit()

    def update_session_summary(self, session_id: str, summary: str) -> None:
        self.connection.execute(
            "UPDATE sessions SET summary=?, updated_at=? WHERE id=?",
            (summary, self.now(), session_id),
        )
        self.connection.commit()

    def set_session_provider_thread(self, session_id: str, thread_id: str) -> None:
        self.connection.execute(
            "UPDATE sessions SET provider_thread_id=?, updated_at=? WHERE id=?",
            (thread_id, self.now(), session_id),
        )
        self.connection.commit()

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        company_id: str | None = None,
        source: str = "terminal",
        trusted: bool = True,
        expires_at: str = "",
        pinned: bool = False,
    ) -> str:
        session = self.session(session_id)
        if not session:
            raise KeyError(session_id)
        session_company = str(session["company_id"])
        if company_id is not None and company_id != session_company:
            raise PermissionError("Message company does not match its session")
        company_id = session_company
        message_id, now = str(uuid.uuid4()), self.now()
        self.connection.execute(
            "INSERT INTO messages "
            "(id, session_id, company_id, role, content, source, trusted, pinned, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                session_id,
                company_id,
                role,
                content,
                source,
                int(trusted),
                int(pinned),
                expires_at,
                now,
            ),
        )
        self.connection.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        self.connection.commit()
        return message_id

    def session_messages(self, session_id: str, limit: int | None = 24) -> list[dict[str, Any]]:
        query = (
            "SELECT id, role, content, source, trusted, pinned, expires_at, created_at "
            "FROM messages WHERE session_id=? ORDER BY created_at DESC"
        )
        params: tuple[Any, ...] = (session_id,)
        if limit is not None:
            query += " LIMIT ?"
            params += (limit,)
        rows = self.connection.execute(query, params).fetchall()
        return [dict(row) for row in reversed(rows)]

    def recent_sessions(self, limit: int = 20, company_id: str | None = None) -> list[dict[str, Any]]:
        where, params = ("WHERE sessions.company_id=? ", (company_id,)) if company_id else ("", ())
        rows = self.connection.execute(
            "SELECT sessions.*, COUNT(messages.id) AS message_count "
            "FROM sessions LEFT JOIN messages ON messages.session_id=sessions.id "
            f"{where}GROUP BY sessions.id ORDER BY sessions.updated_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(row) for row in rows]

    def search_sessions(
        self,
        query: str,
        *,
        company_id: str = "default",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        needle = f"%{query.strip()}%"
        rows = self.connection.execute(
            "SELECT sessions.*, COUNT(messages.id) AS message_count "
            "FROM sessions LEFT JOIN messages ON messages.session_id=sessions.id "
            "WHERE sessions.company_id=? AND (sessions.summary LIKE ? OR messages.content LIKE ?) "
            "GROUP BY sessions.id ORDER BY sessions.updated_at DESC LIMIT ?",
            (company_id, needle, needle, limit),
        )
        return [dict(row) for row in rows]

    def clear_session(self, session_id: str) -> None:
        self.connection.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        self.connection.commit()

    def save_memory(
        self,
        content: str,
        *,
        company_id: str,
        kind: str,
        provenance: str,
        sensitivity: str,
        effective_date: str = "",
        trusted: bool = True,
        pinned: bool = False,
        expires_at: str = "",
        memory_id: str | None = None,
    ) -> dict[str, Any]:
        now = self.now()
        if memory_id:
            current = self.connection.execute(
                "SELECT * FROM memory_items WHERE id=? AND company_id=?",
                (memory_id, company_id),
            ).fetchone()
            if not current:
                raise KeyError(memory_id)
            self.connection.execute(
                "UPDATE memory_items SET kind=?, content=?, provenance=?, sensitivity=?, "
                "effective_date=?, revision=?, trusted=?, pinned=?, expires_at=?, updated_at=? "
                "WHERE id=? AND company_id=?",
                (
                    kind,
                    content,
                    provenance,
                    sensitivity,
                    effective_date,
                    int(current["revision"]) + 1,
                    int(trusted),
                    int(bool(current["pinned"]) or pinned),
                    "" if current["pinned"] or pinned else expires_at,
                    now,
                    memory_id,
                    company_id,
                ),
            )
        else:
            duplicate = self.connection.execute(
                "SELECT * FROM memory_items WHERE company_id=? AND kind=? AND content=?",
                (company_id, kind, content),
            ).fetchone()
            if duplicate:
                self.connection.execute(
                    "UPDATE memory_items SET provenance=?, sensitivity=?, effective_date=?, trusted=?, "
                    "pinned=?, expires_at=?, updated_at=? WHERE id=?",
                    (
                        provenance,
                        sensitivity,
                        effective_date,
                        int(trusted),
                        int(bool(duplicate["pinned"]) or pinned),
                        "" if duplicate["pinned"] or pinned else expires_at,
                        now,
                        duplicate["id"],
                    ),
                )
                self.connection.commit()
                row = self.connection.execute(
                    "SELECT * FROM memory_items WHERE id=?",
                    (duplicate["id"],),
                ).fetchone()
                return dict(row)
            memory_id = str(uuid.uuid4())
            self.connection.execute(
                "INSERT INTO memory_items "
                "(id, company_id, kind, content, provenance, sensitivity, effective_date, revision, "
                "trusted, pinned, expires_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                (
                    memory_id,
                    company_id,
                    kind,
                    content,
                    provenance,
                    sensitivity,
                    effective_date,
                    int(trusted),
                    int(pinned),
                    expires_at,
                    now,
                    now,
                ),
            )
        self.connection.commit()
        row = self.connection.execute("SELECT * FROM memory_items WHERE id=?", (memory_id,)).fetchone()
        return dict(row)

    def memory_items(
        self,
        *,
        company_id: str,
        query: str = "",
        limit: int = 50,
        include_global: bool = True,
    ) -> list[dict[str, Any]]:
        company_ids = [company_id]
        if include_global and company_id != "__global__":
            company_ids.append("__global__")
        placeholders = ",".join("?" for _ in company_ids)
        params: list[Any] = [*company_ids, self.now()]
        sql = (
            f"SELECT * FROM memory_items WHERE company_id IN ({placeholders}) "
            "AND (pinned=1 OR expires_at='' OR expires_at>?)"
        )
        if query.strip():
            sql += " AND content LIKE ?"
            params.append(f"%{query.strip()}%")
        sql += " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self.connection.execute(sql, params)]

    def forget_memory(self, memory_id: str, *, company_id: str, reason: str = "user_request") -> bool:
        row = self.connection.execute(
            "SELECT content FROM memory_items WHERE id=? AND company_id=?",
            (memory_id, company_id),
        ).fetchone()
        if not row:
            return False
        self.connection.execute(
            "INSERT OR IGNORE INTO memory_tombstones VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                memory_id,
                company_id,
                hashlib.sha256(row["content"].encode("utf-8")).hexdigest(),
                reason,
                self.now(),
            ),
        )
        self.connection.execute("DELETE FROM memory_items WHERE id=? AND company_id=?", (memory_id, company_id))
        self.connection.commit()
        return True

    def memory_tombstone(self, memory_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM memory_tombstones WHERE memory_id=?",
            (memory_id,),
        ).fetchone()
        return dict(row) if row else None

    def pin_memory(
        self,
        memory_id: str,
        *,
        company_id: str,
        pinned: bool = True,
        expires_at: str = "",
    ) -> bool:
        cursor = self.connection.execute(
            "UPDATE memory_items SET pinned=?, expires_at=?, updated_at=? WHERE id=? AND company_id=?",
            (int(pinned), "" if pinned else expires_at, self.now(), memory_id, company_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def memory_scopes(self) -> set[str]:
        rows = self.connection.execute(
            "SELECT company_id FROM memory_items UNION SELECT company_id FROM memory_tombstones"
        )
        return {str(row["company_id"]) for row in rows}

    def pin_message(
        self,
        message_id: str,
        *,
        company_id: str,
        pinned: bool = True,
        expires_at: str = "",
    ) -> bool:
        cursor = self.connection.execute(
            "UPDATE messages SET pinned=?, expires_at=? WHERE id=? AND company_id=?",
            (int(pinned), "" if pinned else expires_at, message_id, company_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def purge_expired(self, *, now: str | None = None) -> dict[str, int]:
        cutoff = now or self.now()
        expired = self.connection.execute(
            "SELECT id, company_id FROM memory_items WHERE pinned=0 AND expires_at!='' AND expires_at<=?",
            (cutoff,),
        ).fetchall()
        for row in expired:
            self.forget_memory(row["id"], company_id=row["company_id"], reason="retention")
        cursor = self.connection.execute(
            "DELETE FROM messages WHERE pinned=0 AND expires_at!='' AND expires_at<=?",
            (cutoff,),
        )
        self.connection.commit()
        return {"memory": len(expired), "messages": cursor.rowcount}

    def close(self) -> None:
        self.connection.close()


def runtime_store(
    settings: dict[str, Any],
    *,
    path: Path = MEMORY_DB,
    local_store: JobStore | None = None,
):
    """Keep legacy workflow state local while moving agent state to PostgreSQL."""

    data_plane = settings.get("data_plane", {})
    distributed = bool(
        isinstance(data_plane, dict)
        and (data_plane.get("enabled") or data_plane.get("postgres_dsn"))
    ) or bool(os.getenv("TAXSENTRY_POSTGRES_DSN"))
    local = local_store or JobStore(path)
    if not distributed:
        return local
    try:
        from .data_plane import (
            HybridStore,
            PostgresAgentStore,
            job_queue_from_settings,
        )

        queue = job_queue_from_settings(settings)
        queue.ensure_schema()
        company = settings.get("advisor", {}).get("company", {})
        company_id = str(
            settings.get("agent", {}).get("company_id")
            or company.get("id")
            or "default"
        )
        agent = PostgresAgentStore(
            queue,
            company_id=company_id,
            retention_days=int(
                settings.get("memory", {}).get("retention_days", 90)
            ),
        )
        agent.upsert_company(
            name=str(company.get("name") or ""),
            country_code=str(company.get("country_code") or "VN"),
            currency=str(company.get("currency") or "VND"),
            profile=company,
        )
        return HybridStore(local, agent)
    except Exception:
        local.close()
        raise
