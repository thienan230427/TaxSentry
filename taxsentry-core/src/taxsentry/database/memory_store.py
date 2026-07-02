from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from taxsentry.config.paths import DB_PATH
from taxsentry.text_normalize import tokens_for_match, normalize_for_match


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    memory_type: str
    subject: str
    summary: str
    payload: dict[str, Any]
    tags: list[str]
    confidence: float
    importance: float
    source_ref: str | None
    created_at: str
    updated_at: str


class TaxSentryMemoryStore:
    """SQLite-backed persistent memory store for stable user/project/decision facts."""

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

    def _init_db(self) -> None:
        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_store (
                memory_id TEXT PRIMARY KEY,
                memory_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                summary TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                importance REAL NOT NULL,
                source_ref TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_store(memory_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_subject ON memory_store(subject)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memory_created_at ON memory_store(created_at)")
        self.connection.commit()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_tags(tags: list[str] | tuple[str, ...] | None) -> list[str]:
        if not tags:
            return []
        normalized = []
        for tag in tags:
            value = str(tag).strip()
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    def remember(
        self,
        *,
        memory_type: str,
        subject: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        confidence: float = 1.0,
        importance: float = 0.5,
        source_ref: str | None = None,
    ) -> str:
        if not self._ensure_connection():
            raise RuntimeError("Memory store is not available")

        memory_id = f"mem_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        now = self._utc_now()
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        tags_json = json.dumps(self._normalize_tags(tags), ensure_ascii=False)

        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO memory_store (
                memory_id, memory_type, subject, summary, payload_json, tags_json,
                confidence, importance, source_ref, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                memory_type,
                subject,
                summary,
                payload_json,
                tags_json,
                float(confidence),
                float(importance),
                source_ref,
                now,
                now,
            ),
        )
        self.connection.commit()
        return memory_id

    def recall(
        self,
        query: str,
        *,
        scope: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        if not self._ensure_connection():
            return []

        tokens = tokens_for_match(query)
        normalized_query = normalize_for_match(query)
        assert self.connection is not None
        cursor = self.connection.cursor()
        if scope:
            cursor.execute(
                """
                SELECT * FROM memory_store
                WHERE memory_type = ?
                """,
                (scope,),
            )
        else:
            cursor.execute("SELECT * FROM memory_store")
        rows = cursor.fetchall()

        scored_rows: list[tuple[float, dict[str, Any]]] = []
        now = datetime.now(timezone.utc)
        for row in rows:
            record = self._row_to_record(row)
            score = self._score_record(record, tokens, normalized_query, now)
            if score <= 0:
                continue
            scored_rows.append((score, self._record_to_dict(record)))

        scored_rows.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored_rows[:limit]]

    def forget(self, memory_id: str) -> bool:
        if not self._ensure_connection():
            return False

        assert self.connection is not None
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM memory_store WHERE memory_id = ?", (memory_id,))
        self.connection.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row["memory_id"],
            memory_type=row["memory_type"],
            subject=row["subject"],
            summary=row["summary"],
            payload=json.loads(row["payload_json"] or "{}"),
            tags=json.loads(row["tags_json"] or "[]"),
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            source_ref=row["source_ref"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _record_to_dict(record: MemoryRecord) -> dict[str, Any]:
        return {
            "memory_id": record.memory_id,
            "memory_type": record.memory_type,
            "subject": record.subject,
            "summary": record.summary,
            "payload": record.payload,
            "tags": record.tags,
            "confidence": record.confidence,
            "importance": record.importance,
            "source_ref": record.source_ref,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    @staticmethod
    def _score_record(record: MemoryRecord, tokens: list[str], normalized_query: str, now: datetime) -> float:
        haystack = " ".join(
            [
                record.memory_type,
                record.subject,
                record.summary,
                " ".join(record.tags),
                json.dumps(record.payload, ensure_ascii=False),
            ]
        )
        haystack_lower = haystack.lower()
        normalized_haystack = normalize_for_match(haystack)
        relevance = sum(1 for token in tokens if token in haystack_lower)
        relevance += sum(1 for token in tokens if token in normalized_haystack)
        semantic_similarity = TaxSentryMemoryStore._trigram_similarity(normalized_query, normalized_haystack)
        if not relevance and semantic_similarity < 0.08:
            return 0.0

        created_at = datetime.fromisoformat(record.created_at)
        age_seconds = max((now - created_at).total_seconds(), 0.0)
        recency = 1.0 / (1.0 + age_seconds / 86400.0)
        return (
            (relevance * 2.0)
            + (semantic_similarity * 4.0)
            + (record.importance * 1.5)
            + (record.confidence * 1.0)
            + (recency * 0.5)
        )

    @staticmethod
    def _trigram_similarity(left: str, right: str) -> float:
        left = " ".join(left.split())
        right = " ".join(right.split())
        if len(left) < 3 or len(right) < 3:
            return 0.0
        left_grams = {left[index : index + 3] for index in range(len(left) - 2)}
        right_grams = {right[index : index + 3] for index in range(len(right) - 2)}
        if not left_grams or not right_grams:
            return 0.0
        return len(left_grams & right_grams) / math.sqrt(len(left_grams) * len(right_grams))
