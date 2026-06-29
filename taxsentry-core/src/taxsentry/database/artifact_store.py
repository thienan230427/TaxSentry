from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from taxsentry.config.paths import DB_PATH


class TaxSentryArtifactStore:
    """SQLite-backed artifact registry with provenance metadata."""

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
            CREATE TABLE IF NOT EXISTS artifact_store (
                artifact_id TEXT PRIMARY KEY,
                session_id TEXT,
                event_id TEXT,
                trace_id TEXT,
                artifact_type TEXT NOT NULL,
                artifact_name TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                source_file TEXT,
                source_path TEXT,
                mime_type TEXT,
                size_bytes INTEGER,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifact_store_session_id ON artifact_store(session_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifact_store_trace_id ON artifact_store(trace_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifact_store_created_at ON artifact_store(created_at)")
        self.connection.commit()

    def register_artifact(
        self,
        *,
        artifact_type: str,
        artifact_name: str,
        artifact_path: str | Path,
        session_id: str | None = None,
        event_id: str | None = None,
        trace_id: str | None = None,
        source_file: str | None = None,
        source_path: str | None = None,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        if not self._ensure_connection():
            raise RuntimeError("Artifact store is not available")

        artifact_id = uuid.uuid4().hex[:12]
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        artifact_path_text = str(Path(artifact_path))
        if size_bytes is None:
            try:
                size_bytes = Path(artifact_path_text).stat().st_size
            except Exception:
                size_bytes = None

        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO artifact_store (
                artifact_id, session_id, event_id, trace_id,
                artifact_type, artifact_name, artifact_path,
                source_file, source_path, mime_type, size_bytes,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                session_id,
                event_id,
                trace_id,
                artifact_type,
                artifact_name,
                artifact_path_text,
                source_file,
                source_path,
                mime_type,
                size_bytes,
                metadata_json,
                self._utc_now(),
            ),
        )
        self.connection.commit()
        return artifact_id

    def get_recent_artifacts(self, limit: int = 10) -> list[dict[str, Any]]:
        if not self._ensure_connection():
            return []

        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT *
            FROM artifact_store
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_session_artifacts(self, session_id: str) -> list[dict[str, Any]]:
        if not self._ensure_connection():
            return []

        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT *
            FROM artifact_store
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        if item.get("metadata_json"):
            try:
                item["metadata"] = json.loads(item.pop("metadata_json"))
            except Exception:
                item["metadata"] = {}
        else:
            item["metadata"] = {}
        return item
