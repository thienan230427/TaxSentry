from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from taxsentry.config.paths import DB_PATH


class TaxSentrySessionStore:
    """SQLite-backed session and event store for audit/replay traces."""

    def __init__(self, db_path: str | None = None):
        self.db_path = str(db_path or DB_PATH)
        self.connection: sqlite3.Connection | None = None

    def connect(self) -> bool:
        try:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
            self._init_db()
            return True
        except Exception:
            self.connection = None
            return False

    def close(self) -> None:
        if self.connection:
            try:
                self.connection.close()
            finally:
                self.connection = None

    def _ensure_connection(self) -> bool:
        return bool(self.connection or self.connect())

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _init_db(self) -> None:
        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS session_store (
                session_id TEXT PRIMARY KEY,
                entry_point TEXT NOT NULL,
                mode TEXT NOT NULL,
                title TEXT,
                summary TEXT,
                outcome TEXT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS event_log (
                event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                result TEXT,
                latency_ms REAL,
                error_message TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES session_store(session_id)
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_store_started_at ON session_store(started_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_log_session_id ON event_log(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at)")
        self.connection.commit()

    def start_session(
        self,
        *,
        entry_point: str,
        mode: str,
        title: str | None = None,
        summary: str | None = None,
    ) -> str:
        if not self._ensure_connection():
            raise RuntimeError("Session store is not available")

        session_id = uuid.uuid4().hex[:12]
        now = self._utc_now()
        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO session_store (
                session_id, entry_point, mode, title, summary, outcome,
                started_at, ended_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                entry_point,
                mode,
                title,
                summary,
                None,
                now,
                None,
                now,
                now,
            ),
        )
        self.connection.commit()
        return session_id

    def end_session(self, session_id: str, *, summary: str | None = None, outcome: str | None = None) -> bool:
        if not self._ensure_connection():
            return False

        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            UPDATE session_store
            SET summary = COALESCE(?, summary),
                outcome = COALESCE(?, outcome),
                ended_at = ?,
                updated_at = ?
            WHERE session_id = ?
            """,
            (summary, outcome, self._utc_now(), self._utc_now(), session_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def log_event(
        self,
        *,
        session_id: str,
        event_type: str,
        actor: str,
        action: str,
        result: str | None = None,
        latency_ms: float | None = None,
        error_message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        if not self._ensure_connection():
            raise RuntimeError("Session store is not available")

        event_id = uuid.uuid4().hex[:10]
        payload_json = json.dumps(payload or {}, ensure_ascii=False, default=str)
        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO event_log (
                event_id, session_id, event_type, actor, action,
                result, latency_ms, error_message, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                session_id,
                event_type,
                actor,
                action,
                result,
                latency_ms,
                error_message,
                payload_json,
                self._utc_now(),
            ),
        )
        self.connection.commit()
        return event_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        if not self._ensure_connection():
            return None

        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT *
            FROM session_store
            WHERE session_id = ?
            LIMIT 1
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        if not self._ensure_connection():
            return []

        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT *
            FROM session_store
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_session_events(self, session_id: str) -> list[dict[str, Any]]:
        if not self._ensure_connection():
            return []

        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT *
            FROM event_log
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        events = []
        for row in cursor.fetchall():
            event = dict(row)
            if event.get("payload_json"):
                try:
                    event["payload"] = json.loads(event.pop("payload_json"))
                except Exception:
                    event["payload"] = {}
            else:
                event["payload"] = {}
            events.append(event)
        return events
