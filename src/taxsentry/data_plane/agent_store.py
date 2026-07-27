from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..prompt import safe_company_id
from .queue import PostgresJobQueue

GLOBAL_MEMORY_SCOPE = "__global__"


class PostgresAgentStore:
    """Company-scoped PostgreSQL session and memory store."""

    def __init__(
        self,
        queue: PostgresJobQueue,
        *,
        company_id: str = "default",
        retention_days: int = 90,
    ) -> None:
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        self.queue = queue
        self.company_id = safe_company_id(company_id)
        self.retention_days = retention_days

    def upsert_company(
        self,
        company_id: str | None = None,
        *,
        name: str = "",
        country_code: str = "VN",
        currency: str = "VND",
        profile: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        company = self._memory_scope(company_id or self.company_id)
        country_code, currency = country_code.upper(), currency.upper()
        if len(country_code) != 2 or not country_code.isalpha():
            raise ValueError("country_code must be ISO alpha-2")
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("currency must be ISO alpha-3")
        now = self.now()
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO taxsentry.companies
                    (id, name, country_code, currency, profile, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name=excluded.name,
                    country_code=excluded.country_code,
                    currency=excluded.currency,
                    profile=excluded.profile,
                    updated_at=excluded.updated_at
                RETURNING *
                """,
                (
                    company,
                    name,
                    country_code,
                    currency,
                    json.dumps(dict(profile or {}), ensure_ascii=False),
                    now,
                    now,
                ),
            )
            return _row(cursor.fetchone())

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
        company = self._company_scope(company_id)
        session_id, now = str(uuid.uuid4()), self.now()
        with self.queue._connect() as connection, connection.cursor() as cursor:
            self._ensure_company(cursor, company, now)
            cursor.execute(
                """
                INSERT INTO taxsentry.sessions
                    (id, company_id, platform, provider, model, system_prompt_hash,
                     system_prompt, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    company,
                    platform,
                    provider,
                    model,
                    system_prompt_hash,
                    system_prompt,
                    now,
                    now,
                ),
            )
        return session_id

    def session(self, session_id: str) -> dict[str, Any] | None:
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT sessions.*, COALESCE(session_summaries.summary, '') AS summary
                FROM taxsentry.sessions
                LEFT JOIN taxsentry.session_summaries
                    ON session_summaries.session_id=sessions.id
                WHERE sessions.id=%s AND sessions.company_id=%s
                """,
                (session_id, self.company_id),
            )
            row = cursor.fetchone()
        return _row(row) if row else None

    def update_session_prompt(
        self,
        session_id: str,
        prompt: str,
        prompt_digest: str,
    ) -> None:
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE taxsentry.sessions
                SET system_prompt=%s, system_prompt_hash=%s, updated_at=%s
                WHERE id=%s AND company_id=%s
                """,
                (prompt, prompt_digest, self.now(), session_id, self.company_id),
            )

    def update_session_summary(self, session_id: str, summary: str) -> None:
        now = self.now()
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO taxsentry.session_summaries
                    (session_id, company_id, summary, updated_at)
                SELECT id, company_id, %s, %s
                FROM taxsentry.sessions
                WHERE id=%s AND company_id=%s
                ON CONFLICT (session_id) DO UPDATE SET
                    summary=excluded.summary,
                    updated_at=excluded.updated_at
                """,
                (summary, now, session_id, self.company_id),
            )
            cursor.execute(
                """
                UPDATE taxsentry.sessions SET updated_at=%s
                WHERE id=%s AND company_id=%s
                """,
                (now, session_id, self.company_id),
            )

    def set_session_provider_thread(self, session_id: str, thread_id: str) -> None:
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE taxsentry.sessions
                SET provider_thread_id=%s, updated_at=%s
                WHERE id=%s AND company_id=%s
                """,
                (thread_id, self.now(), session_id, self.company_id),
            )

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
        if company_id is not None:
            self._company_scope(company_id)
        message_id, now = str(uuid.uuid4()), self.now()
        expiry = self._expiry(expires_at, pinned, now)
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM taxsentry.sessions
                WHERE id=%s AND company_id=%s
                FOR UPDATE
                """,
                (session_id, self.company_id),
            )
            if not cursor.fetchone():
                raise KeyError(session_id)
            cursor.execute(
                """
                INSERT INTO taxsentry.messages
                    (id, session_id, company_id, role, content, source, trusted,
                     pinned, expires_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    message_id,
                    session_id,
                    self.company_id,
                    role,
                    content,
                    source,
                    bool(trusted),
                    bool(pinned),
                    expiry,
                    now,
                ),
            )
            cursor.execute(
                """
                UPDATE taxsentry.sessions SET updated_at=%s
                WHERE id=%s AND company_id=%s
                """,
                (now, session_id, self.company_id),
            )
        return message_id

    def session_messages(
        self,
        session_id: str,
        limit: int | None = 24,
    ) -> list[dict[str, Any]]:
        if limit is not None and limit <= 0:
            return []
        with self.queue._connect() as connection, connection.cursor() as cursor:
            if limit is None:
                cursor.execute(
                    """
                    SELECT messages.id, messages.role, messages.content,
                           messages.source, messages.trusted, messages.pinned,
                           messages.expires_at, messages.created_at
                    FROM taxsentry.messages
                    JOIN taxsentry.sessions ON sessions.id=messages.session_id
                    WHERE messages.session_id=%s
                      AND messages.company_id=%s
                      AND sessions.company_id=%s
                    ORDER BY messages.created_at, messages.id
                    """,
                    (session_id, self.company_id, self.company_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM (
                        SELECT messages.id, messages.role, messages.content,
                               messages.source, messages.trusted, messages.pinned,
                               messages.expires_at, messages.created_at
                        FROM taxsentry.messages
                        JOIN taxsentry.sessions ON sessions.id=messages.session_id
                        WHERE messages.session_id=%s
                          AND messages.company_id=%s
                          AND sessions.company_id=%s
                        ORDER BY messages.created_at DESC, messages.id DESC
                        LIMIT %s
                    ) AS recent
                    ORDER BY created_at, id
                    """,
                    (session_id, self.company_id, self.company_id, limit),
                )
            return [_row(row) for row in cursor.fetchall()]

    def search_sessions(
        self,
        query: str,
        *,
        company_id: str = "default",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        company = self._company_scope(company_id)
        if limit <= 0:
            return []
        needle = f"%{query.strip()}%"
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT sessions.*,
                       COALESCE(session_summaries.summary, '') AS summary,
                       (
                           SELECT COUNT(*) FROM taxsentry.messages AS counted
                           WHERE counted.session_id=sessions.id
                             AND counted.company_id=sessions.company_id
                       ) AS message_count
                FROM taxsentry.sessions
                LEFT JOIN taxsentry.session_summaries
                    ON session_summaries.session_id=sessions.id
                WHERE sessions.company_id=%s
                  AND (
                      COALESCE(session_summaries.summary, '') ILIKE %s
                      OR EXISTS (
                          SELECT 1 FROM taxsentry.messages AS searched
                          WHERE searched.session_id=sessions.id
                            AND searched.company_id=sessions.company_id
                            AND searched.content ILIKE %s
                      )
                  )
                ORDER BY sessions.updated_at DESC
                LIMIT %s
                """,
                (company, needle, needle, limit),
            )
            return [_row(row) for row in cursor.fetchall()]

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
        company = self._memory_scope(company_id)
        now = self.now()
        expiry = self._expiry(expires_at, pinned, now)
        provenance_json = _jsonb(provenance)
        with self.queue._connect() as connection, connection.cursor() as cursor:
            self._ensure_company(cursor, company, now)
            if memory_id:
                cursor.execute(
                    """
                    SELECT * FROM taxsentry.memory_items
                    WHERE id=%s AND company_id=%s
                    FOR UPDATE
                    """,
                    (memory_id, company),
                )
                current = cursor.fetchone()
                if not current:
                    raise KeyError(memory_id)
                keep_pinned = bool(current["pinned"]) or pinned
                cursor.execute(
                    """
                    UPDATE taxsentry.memory_items
                    SET kind=%s, content=%s, provenance=%s::jsonb,
                        sensitivity=%s, effective_date=%s, revision=%s,
                        embedding=NULL, trusted=%s, pinned=%s, expires_at=%s,
                        updated_at=%s
                    WHERE id=%s AND company_id=%s
                    RETURNING *
                    """,
                    (
                        kind,
                        content,
                        provenance_json,
                        sensitivity,
                        effective_date or None,
                        int(current["revision"]) + 1,
                        bool(trusted),
                        keep_pinned,
                        None if keep_pinned else expiry,
                        now,
                        memory_id,
                        company,
                    ),
                )
                return _row(cursor.fetchone())
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (
                    json.dumps(
                        [company, kind, content],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            )
            cursor.execute(
                """
                SELECT * FROM taxsentry.memory_items
                WHERE company_id=%s AND kind=%s AND content=%s
                FOR UPDATE
                """,
                (company, kind, content),
            )
            duplicate = cursor.fetchone()
            if duplicate:
                keep_pinned = bool(duplicate["pinned"]) or pinned
                cursor.execute(
                    """
                    UPDATE taxsentry.memory_items
                    SET provenance=%s::jsonb, sensitivity=%s, effective_date=%s,
                        trusted=%s, pinned=%s, expires_at=%s, updated_at=%s
                    WHERE id=%s AND company_id=%s
                    RETURNING *
                    """,
                    (
                        provenance_json,
                        sensitivity,
                        effective_date or None,
                        bool(trusted),
                        keep_pinned,
                        None if keep_pinned else expiry,
                        now,
                        duplicate["id"],
                        company,
                    ),
                )
                return _row(cursor.fetchone())
            memory_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO taxsentry.memory_items
                    (id, company_id, kind, content, provenance, sensitivity,
                     effective_date, revision, trusted, pinned, expires_at,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, 1, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    memory_id,
                    company,
                    kind,
                    content,
                    provenance_json,
                    sensitivity,
                    effective_date or None,
                    bool(trusted),
                    bool(pinned),
                    expiry,
                    now,
                    now,
                ),
            )
            return _row(cursor.fetchone())

    def memory_items(
        self,
        *,
        company_id: str,
        query: str = "",
        limit: int = 50,
        include_global: bool = True,
    ) -> list[dict[str, Any]]:
        company = self._memory_scope(company_id)
        if limit <= 0:
            return []
        scopes = [company]
        if include_global and company != GLOBAL_MEMORY_SCOPE:
            scopes.append(GLOBAL_MEMORY_SCOPE)
        scope_sql = "memory_items.company_id=%s"
        params: list[Any] = [company]
        if len(scopes) == 2:
            scope_sql = "(memory_items.company_id=%s OR memory_items.company_id=%s)"
            params.append(GLOBAL_MEMORY_SCOPE)
        params.extend((self.now(), f"%{query.strip()}%", limit))
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT * FROM taxsentry.memory_items
                WHERE {scope_sql}
                  AND (pinned OR expires_at IS NULL OR expires_at>%s)
                  AND content ILIKE %s
                ORDER BY pinned DESC, updated_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return [_row(row) for row in cursor.fetchall()]

    def forget_memory(
        self,
        memory_id: str,
        *,
        company_id: str,
        reason: str = "user_request",
    ) -> bool:
        company = self._memory_scope(company_id)
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT content FROM taxsentry.memory_items
                WHERE id=%s AND company_id=%s
                FOR UPDATE
                """,
                (memory_id, company),
            )
            row = cursor.fetchone()
            if not row:
                return False
            cursor.execute(
                """
                INSERT INTO taxsentry.memory_tombstones
                    (id, memory_id, company_id, content_hash, reason, deleted_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (memory_id) DO NOTHING
                """,
                (
                    str(uuid.uuid4()),
                    memory_id,
                    company,
                    hashlib.sha256(str(row["content"]).encode()).hexdigest(),
                    reason,
                    self.now(),
                ),
            )
            cursor.execute(
                """
                DELETE FROM taxsentry.memory_items
                WHERE id=%s AND company_id=%s
                """,
                (memory_id, company),
            )
        return True

    def memory_tombstone(self, memory_id: str) -> dict[str, Any] | None:
        scopes = self._memory_scopes()
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM taxsentry.memory_tombstones
                WHERE memory_id=%s AND (company_id=%s OR company_id=%s)
                """,
                (memory_id, scopes[0], scopes[-1]),
            )
            row = cursor.fetchone()
        return _row(row) if row else None

    def pin_memory(
        self,
        memory_id: str,
        *,
        company_id: str,
        pinned: bool = True,
        expires_at: str = "",
    ) -> bool:
        company = self._memory_scope(company_id)
        now = self.now()
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE taxsentry.memory_items
                SET pinned=%s, expires_at=%s, updated_at=%s
                WHERE id=%s AND company_id=%s
                """,
                (
                    bool(pinned),
                    self._expiry(expires_at, pinned, now),
                    now,
                    memory_id,
                    company,
                ),
            )
            return cursor.rowcount > 0

    def memory_scopes(self) -> set[str]:
        scopes = self._memory_scopes()
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT company_id FROM taxsentry.memory_items
                WHERE company_id=%s OR company_id=%s
                UNION
                SELECT company_id FROM taxsentry.memory_tombstones
                WHERE company_id=%s OR company_id=%s
                """,
                (scopes[0], scopes[-1], scopes[0], scopes[-1]),
            )
            allowed = set(scopes)
            return {
                str(row["company_id"])
                for row in cursor.fetchall()
                if str(row["company_id"]) in allowed
            }

    def pin_message(
        self,
        message_id: str,
        *,
        company_id: str,
        pinned: bool = True,
        expires_at: str = "",
    ) -> bool:
        company = self._company_scope(company_id)
        now = self.now()
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE taxsentry.messages
                SET pinned=%s, expires_at=%s
                WHERE id=%s AND company_id=%s
                """,
                (
                    bool(pinned),
                    self._expiry(expires_at, pinned, now),
                    message_id,
                    company,
                ),
            )
            return cursor.rowcount > 0

    def purge_expired(self, *, now: str | None = None) -> dict[str, int]:
        cutoff = now or self.now()
        scopes = self._memory_scopes()
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, company_id, content
                FROM taxsentry.memory_items
                WHERE (company_id=%s OR company_id=%s)
                  AND NOT pinned
                  AND expires_at IS NOT NULL
                  AND expires_at<=%s
                FOR UPDATE
                """,
                (scopes[0], scopes[-1], cutoff),
            )
            expired = cursor.fetchall()
            for row in expired:
                cursor.execute(
                    """
                    INSERT INTO taxsentry.memory_tombstones
                        (id, memory_id, company_id, content_hash, reason, deleted_at)
                    VALUES (%s, %s, %s, %s, 'retention', %s)
                    ON CONFLICT (memory_id) DO NOTHING
                    """,
                    (
                        str(uuid.uuid4()),
                        row["id"],
                        row["company_id"],
                        hashlib.sha256(str(row["content"]).encode()).hexdigest(),
                        cutoff,
                    ),
                )
                cursor.execute(
                    """
                    DELETE FROM taxsentry.memory_items
                    WHERE id=%s AND company_id=%s
                    """,
                    (row["id"], row["company_id"]),
                )
            cursor.execute(
                """
                DELETE FROM taxsentry.messages
                WHERE company_id=%s
                  AND NOT pinned
                  AND expires_at IS NOT NULL
                  AND expires_at<=%s
                """,
                (self.company_id, cutoff),
            )
            messages = cursor.rowcount
        return {"memory": len(expired), "messages": messages}

    def close(self) -> None:
        # Connections are scoped to each operation by PostgresJobQueue.
        return None

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _company_scope(self, company_id: str) -> str:
        company = safe_company_id(company_id)
        if company != self.company_id:
            raise PermissionError("Company scope does not match this store")
        return company

    def _memory_scope(self, company_id: str) -> str:
        if company_id == GLOBAL_MEMORY_SCOPE:
            return company_id
        return self._company_scope(company_id)

    def _memory_scopes(self) -> tuple[str, str]:
        return self.company_id, GLOBAL_MEMORY_SCOPE

    def _expiry(self, value: str, pinned: bool, now: str) -> str | None:
        if pinned:
            return None
        if value:
            return value
        start = datetime.fromisoformat(now.replace("Z", "+00:00"))
        return (start + timedelta(days=self.retention_days)).isoformat()

    @staticmethod
    def _ensure_company(cursor, company_id: str, now: str) -> None:
        cursor.execute(
            """
            INSERT INTO taxsentry.companies (id, created_at, updated_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (company_id, now, now),
        )


class HybridStore:
    """Use PostgreSQL for agent state and the local store for legacy workflow state."""

    _AGENT_METHODS = frozenset(
        {
            "add_message",
            "create_session",
            "forget_memory",
            "memory_items",
            "memory_scopes",
            "memory_tombstone",
            "pin_memory",
            "pin_message",
            "purge_expired",
            "save_memory",
            "search_sessions",
            "session",
            "session_messages",
            "set_session_provider_thread",
            "update_session_prompt",
            "update_session_summary",
            "upsert_company",
        }
    )

    def __init__(self, local_store: Any, agent_store: PostgresAgentStore) -> None:
        self.local_store = local_store
        self.agent_store = agent_store

    def __getattr__(self, name: str):
        target = self.agent_store if name in self._AGENT_METHODS else self.local_store
        return getattr(target, name)

    def close(self) -> None:
        self.agent_store.close()
        self.local_store.close()


def _jsonb(value: str) -> str:
    try:
        json.loads(value)
    except json.JSONDecodeError:
        return json.dumps(value, ensure_ascii=False)
    return value


def _row(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in dict(value).items():
        if isinstance(item, uuid.UUID):
            result[key] = str(item)
        elif isinstance(item, datetime):
            result[key] = item.isoformat()
        elif isinstance(item, date):
            result[key] = item.isoformat()
        elif key == "provenance" and not isinstance(item, str):
            result[key] = json.dumps(item, ensure_ascii=False, sort_keys=True)
        elif item is None and key in {"effective_date", "expires_at"}:
            result[key] = ""
        else:
            result[key] = item
    return result
