from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import Any


class DataPlaneDependencyError(RuntimeError):
    """Raised when an optional data-plane dependency is unavailable."""


class LostLeaseError(RuntimeError):
    """Raised when a worker no longer owns a job lease."""


SCHEMA_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE SCHEMA IF NOT EXISTS taxsentry",
    """
    CREATE TABLE IF NOT EXISTS taxsentry.jobs (
        id uuid PRIMARY KEY,
        company_id text NOT NULL,
        case_id text,
        idempotency_key text NOT NULL,
        state text NOT NULL DEFAULT 'queued'
            CHECK (state IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
        priority integer NOT NULL DEFAULT 0,
        payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        result jsonb NOT NULL DEFAULT '{}'::jsonb,
        budget jsonb NOT NULL DEFAULT '{}'::jsonb,
        attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
        max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
        error text NOT NULL DEFAULT '',
        cancel_requested boolean NOT NULL DEFAULT false,
        available_at timestamptz NOT NULL DEFAULT now(),
        leased_by text,
        lease_token uuid,
        lease_expires_at timestamptz,
        heartbeat_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (company_id, idempotency_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS jobs_claim_idx
    ON taxsentry.jobs (priority DESC, available_at, created_at)
    WHERE state IN ('queued', 'running') AND cancel_requested = false
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.job_steps (
        id uuid PRIMARY KEY,
        job_id uuid NOT NULL REFERENCES taxsentry.jobs(id) ON DELETE CASCADE,
        name text NOT NULL,
        state text NOT NULL DEFAULT 'running'
            CHECK (state IN ('running', 'completed', 'failed')),
        checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
        processed bigint NOT NULL DEFAULT 0 CHECK (processed >= 0),
        total bigint CHECK (total IS NULL OR total >= 0),
        error text NOT NULL DEFAULT '',
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (job_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.job_leases (
        id uuid PRIMARY KEY,
        job_id uuid NOT NULL REFERENCES taxsentry.jobs(id) ON DELETE CASCADE,
        worker_id text NOT NULL,
        acquired_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        released_at timestamptz,
        release_reason text NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS job_leases_job_idx
    ON taxsentry.job_leases (job_id, acquired_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.job_events (
        id uuid PRIMARY KEY,
        job_id uuid NOT NULL REFERENCES taxsentry.jobs(id) ON DELETE CASCADE,
        kind text NOT NULL,
        payload jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS job_events_job_idx
    ON taxsentry.job_events (job_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.deliveries (
        id uuid PRIMARY KEY,
        job_id uuid NOT NULL REFERENCES taxsentry.jobs(id) ON DELETE CASCADE,
        channel text NOT NULL,
        external_id text NOT NULL DEFAULT '',
        status text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS deliveries_sent_once_idx
    ON taxsentry.deliveries (job_id, channel)
    WHERE status = 'sent'
    """,
) + (
    """
    CREATE TABLE IF NOT EXISTS taxsentry.companies (
        id text PRIMARY KEY,
        name text NOT NULL DEFAULT '',
        country_code char(2) NOT NULL DEFAULT 'VN',
        currency char(3) NOT NULL DEFAULT 'VND',
        profile jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.sessions (
        id uuid PRIMARY KEY,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        platform text NOT NULL,
        provider text NOT NULL,
        model text NOT NULL DEFAULT '',
        system_prompt_hash char(64) NOT NULL,
        system_prompt text NOT NULL,
        provider_thread_id text NOT NULL DEFAULT '',
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.messages (
        id uuid PRIMARY KEY,
        session_id uuid NOT NULL REFERENCES taxsentry.sessions(id) ON DELETE CASCADE,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        role text NOT NULL,
        content text NOT NULL,
        source text NOT NULL,
        trusted boolean NOT NULL DEFAULT false,
        pinned boolean NOT NULL DEFAULT false,
        expires_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS messages_company_session_idx
    ON taxsentry.messages (company_id, session_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS messages_search_idx
    ON taxsentry.messages USING gin (to_tsvector('simple', content))
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.session_summaries (
        session_id uuid PRIMARY KEY REFERENCES taxsentry.sessions(id) ON DELETE CASCADE,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        summary text NOT NULL,
        decisions jsonb NOT NULL DEFAULT '[]'::jsonb,
        citations jsonb NOT NULL DEFAULT '[]'::jsonb,
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.memory_items (
        id uuid PRIMARY KEY,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        kind text NOT NULL,
        content text NOT NULL,
        provenance jsonb NOT NULL,
        sensitivity text NOT NULL,
        effective_date date,
        revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
        embedding vector(1536),
        trusted boolean NOT NULL DEFAULT false,
        pinned boolean NOT NULL DEFAULT false,
        expires_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS memory_company_search_idx
    ON taxsentry.memory_items USING gin (to_tsvector('simple', content))
    """,
    """
    CREATE INDEX IF NOT EXISTS memory_company_trgm_idx
    ON taxsentry.memory_items USING gin (content gin_trgm_ops)
    """,
    """
    CREATE INDEX IF NOT EXISTS memory_embedding_idx
    ON taxsentry.memory_items USING hnsw (embedding vector_cosine_ops)
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.memory_tombstones (
        id uuid PRIMARY KEY,
        memory_id uuid NOT NULL UNIQUE,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        content_hash char(64) NOT NULL,
        reason text NOT NULL,
        deleted_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.cases (
        id text PRIMARY KEY,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        status text NOT NULL DEFAULT 'ingesting',
        budget jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.documents (
        id text PRIMARY KEY,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        sha256 char(64) NOT NULL,
        name text NOT NULL,
        mime_type text NOT NULL,
        size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
        raw_object_key text NOT NULL,
        manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
        expires_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (company_id, sha256)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.case_documents (
        case_id text NOT NULL REFERENCES taxsentry.cases(id) ON DELETE CASCADE,
        document_id text NOT NULL REFERENCES taxsentry.documents(id),
        position integer NOT NULL DEFAULT 0,
        PRIMARY KEY (case_id, document_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.document_units (
        id text PRIMARY KEY,
        document_id text NOT NULL REFERENCES taxsentry.documents(id) ON DELETE CASCADE,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        kind text NOT NULL,
        ordinal integer NOT NULL,
        locator text NOT NULL,
        content text NOT NULL DEFAULT '',
        structured jsonb NOT NULL DEFAULT '{}'::jsonb,
        object_key text NOT NULL DEFAULT '',
        status text NOT NULL,
        error text NOT NULL DEFAULT '',
        embedding vector(1536),
        created_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (document_id, kind, ordinal, locator)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS document_units_search_idx
    ON taxsentry.document_units USING gin (to_tsvector('simple', content))
    """,
    """
    CREATE INDEX IF NOT EXISTS document_units_trgm_idx
    ON taxsentry.document_units USING gin (content gin_trgm_ops)
    """,
    """
    CREATE INDEX IF NOT EXISTS document_units_embedding_idx
    ON taxsentry.document_units USING hnsw (embedding vector_cosine_ops)
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.sources (
        id text PRIMARY KEY,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        document_id text REFERENCES taxsentry.documents(id) ON DELETE CASCADE,
        kind text NOT NULL,
        title text NOT NULL,
        locator text NOT NULL,
        effective_from date,
        fetched_at timestamptz,
        verified_current boolean NOT NULL DEFAULT false,
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.claims (
        id uuid PRIMARY KEY,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        case_id text REFERENCES taxsentry.cases(id) ON DELETE CASCADE,
        claim_type text NOT NULL CHECK (claim_type IN ('numeric', 'legal', 'narrative')),
        statement text NOT NULL,
        value jsonb,
        assumption boolean NOT NULL DEFAULT false,
        missing_data boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.citations (
        claim_id uuid NOT NULL REFERENCES taxsentry.claims(id) ON DELETE CASCADE,
        source_id text NOT NULL REFERENCES taxsentry.sources(id),
        locator text NOT NULL,
        bounding_box jsonb,
        PRIMARY KEY (claim_id, source_id, locator)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.jurisdiction_packs (
        id text PRIMARY KEY,
        country_code char(2) NOT NULL,
        version text NOT NULL,
        effective_date date NOT NULL,
        manifest jsonb NOT NULL,
        checksum char(64) NOT NULL,
        signature text NOT NULL DEFAULT '',
        verified boolean NOT NULL DEFAULT false,
        refreshed_at timestamptz,
        UNIQUE (country_code, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.knowledge_sources (
        id text PRIMARY KEY,
        pack_id text NOT NULL REFERENCES taxsentry.jurisdiction_packs(id) ON DELETE CASCADE,
        title text NOT NULL,
        locator text NOT NULL,
        trust_score real NOT NULL DEFAULT 1,
        effective_from date,
        fetched_at timestamptz,
        checksum char(64) NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.knowledge_chunks (
        id uuid PRIMARY KEY,
        source_id text NOT NULL REFERENCES taxsentry.knowledge_sources(id) ON DELETE CASCADE,
        content text NOT NULL,
        exact_refs text[] NOT NULL DEFAULT '{}',
        embedding vector(1536),
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS knowledge_chunks_search_idx
    ON taxsentry.knowledge_chunks USING gin (to_tsvector('simple', content))
    """,
    """
    CREATE INDEX IF NOT EXISTS knowledge_chunks_trgm_idx
    ON taxsentry.knowledge_chunks USING gin (content gin_trgm_ops)
    """,
    """
    CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx
    ON taxsentry.knowledge_chunks USING hnsw (embedding vector_cosine_ops)
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.artifacts (
        id uuid PRIMARY KEY,
        company_id text NOT NULL REFERENCES taxsentry.companies(id),
        case_id text REFERENCES taxsentry.cases(id),
        kind text NOT NULL,
        object_key text NOT NULL,
        sha256 char(64) NOT NULL,
        spec jsonb NOT NULL,
        status text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.artifact_sources (
        artifact_id uuid NOT NULL REFERENCES taxsentry.artifacts(id) ON DELETE CASCADE,
        source_id text NOT NULL REFERENCES taxsentry.sources(id),
        PRIMARY KEY (artifact_id, source_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.skills (
        id text PRIMARY KEY,
        name text NOT NULL UNIQUE,
        enabled_version text,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.skill_versions (
        skill_id text NOT NULL REFERENCES taxsentry.skills(id) ON DELETE CASCADE,
        version text NOT NULL,
        manifest jsonb NOT NULL,
        checksum char(64) NOT NULL,
        signature text NOT NULL DEFAULT '',
        source_commit char(40),
        status text NOT NULL CHECK (status IN ('draft', 'approved', 'disabled')),
        approved_by text NOT NULL DEFAULT '',
        approved_at timestamptz,
        PRIMARY KEY (skill_id, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.skill_permissions (
        skill_id text NOT NULL,
        version text NOT NULL,
        permission text NOT NULL,
        scope jsonb NOT NULL DEFAULT '{}'::jsonb,
        approved boolean NOT NULL DEFAULT false,
        PRIMARY KEY (skill_id, version, permission),
        FOREIGN KEY (skill_id, version)
            REFERENCES taxsentry.skill_versions(skill_id, version) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS taxsentry.audit_events (
        id uuid PRIMARY KEY,
        company_id text NOT NULL,
        actor text NOT NULL,
        kind text NOT NULL,
        target_type text NOT NULL,
        target_id text NOT NULL,
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS audit_events_company_created_idx
    ON taxsentry.audit_events (company_id, created_at)
    """,
)


class PostgresJobQueue:
    """PostgreSQL queue with atomic SKIP LOCKED claims and token-bound leases."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        connect: Callable[[], Any] | None = None,
    ) -> None:
        if not dsn and connect is None:
            raise ValueError("PostgreSQL DSN or connect factory is required")
        self.dsn = dsn
        self._connect_factory = connect

    def _connect(self):
        if self._connect_factory is not None:
            return self._connect_factory()
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as exc:
            raise DataPlaneDependencyError(
                "PostgreSQL support requires `psycopg[binary]==3.3.4`"
            ) from exc
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def ensure_schema(self) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                for statement in SCHEMA_STATEMENTS:
                    cursor.execute(statement)
        except DataPlaneDependencyError:
            raise
        except Exception as exc:
            raise RuntimeError(
                "Cannot initialize TaxSentry PostgreSQL schema; ensure pgvector and pg_trgm "
                "are installed and the database role can create extensions"
            ) from exc

    def enqueue(
        self,
        *,
        company_id: str,
        payload: Mapping[str, Any],
        case_id: str | None = None,
        idempotency_key: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        budget: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        _require_text(company_id, "company_id")
        company_id = company_id.strip()
        if case_id is not None:
            _require_text(case_id, "case_id")
            case_id = case_id.strip()
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        job_id = str(uuid.uuid4())
        idempotency_key = idempotency_key or job_id
        _require_text(idempotency_key, "idempotency_key")
        idempotency_key = idempotency_key.strip()
        params = (
            job_id,
            company_id,
            case_id,
            idempotency_key,
            int(priority),
            _json(payload),
            _json(budget or {}),
            max_attempts,
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO taxsentry.jobs
                    (id, company_id, case_id, idempotency_key, priority, payload, budget, max_attempts)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                ON CONFLICT (company_id, idempotency_key) DO NOTHING
                RETURNING *
                """,
                params,
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute(
                    "SELECT * FROM taxsentry.jobs WHERE company_id=%s AND idempotency_key=%s",
                    (company_id, idempotency_key),
                )
                row = cursor.fetchone()
            else:
                self._event(cursor, job_id, "enqueued", {"priority": priority})
        if row is None:
            raise RuntimeError("Job enqueue did not return the inserted or existing job")
        return _row(row)

    def claim(self, worker_id: str, *, lease_seconds: int = 60) -> dict[str, Any] | None:
        _require_text(worker_id, "worker_id")
        worker_id = worker_id.strip()
        _validate_lease_seconds(lease_seconds)
        lease_token = str(uuid.uuid4())
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                WITH candidate AS (
                    SELECT id
                    FROM taxsentry.jobs
                    WHERE attempts < max_attempts
                      AND cancel_requested = false
                      AND available_at <= now()
                      AND (
                          state = 'queued'
                          OR (state = 'running' AND lease_expires_at <= now())
                      )
                    ORDER BY priority DESC, available_at, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE taxsentry.jobs AS job
                SET state='running',
                    attempts=job.attempts + 1,
                    leased_by=%s,
                    lease_token=%s,
                    lease_expires_at=now() + (%s * interval '1 second'),
                    heartbeat_at=now(),
                    updated_at=now()
                FROM candidate
                WHERE job.id=candidate.id
                RETURNING job.*
                """,
                (worker_id, lease_token, lease_seconds),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            job = _row(row)
            cursor.execute(
                """
                UPDATE taxsentry.job_leases
                SET released_at=now(), release_reason='expired'
                WHERE job_id=%s AND released_at IS NULL
                """,
                (job["id"],),
            )
            cursor.execute(
                """
                INSERT INTO taxsentry.job_leases (id, job_id, worker_id, expires_at)
                VALUES (%s, %s, %s, %s)
                """,
                (lease_token, job["id"], worker_id, job["lease_expires_at"]),
            )
            self._event(cursor, str(job["id"]), "claimed", {"worker_id": worker_id})
            return job

    def heartbeat(self, job_id: str, lease_token: str, *, lease_seconds: int = 60) -> bool:
        _validate_uuid(job_id, "job_id")
        _validate_uuid(lease_token, "lease_token")
        _validate_lease_seconds(lease_seconds)
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE taxsentry.jobs
                SET heartbeat_at=now(),
                    lease_expires_at=now() + (%s * interval '1 second'),
                    updated_at=now()
                WHERE id=%s AND lease_token=%s AND state='running' AND lease_expires_at > now()
                RETURNING lease_expires_at
                """,
                (lease_seconds, job_id, lease_token),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            expires_at = _value(row, "lease_expires_at", 0)
            cursor.execute(
                "UPDATE taxsentry.job_leases SET expires_at=%s WHERE id=%s AND released_at IS NULL",
                (expires_at, lease_token),
            )
            return True

    def checkpoint(
        self,
        job_id: str,
        lease_token: str,
        step: str,
        checkpoint: Mapping[str, Any],
        *,
        processed: int = 0,
        total: int | None = None,
        state: str = "running",
        error: str = "",
    ) -> dict[str, Any]:
        _validate_uuid(job_id, "job_id")
        _validate_uuid(lease_token, "lease_token")
        _require_text(step, "step")
        step = step.strip()
        if state not in {"running", "completed", "failed"}:
            raise ValueError("step state must be running, completed, or failed")
        if processed < 0 or (total is not None and (total < 0 or processed > total)):
            raise ValueError("checkpoint progress must satisfy 0 <= processed <= total")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO taxsentry.job_steps
                    (id, job_id, name, state, checkpoint, processed, total, error)
                SELECT %s, id, %s, %s, %s::jsonb, %s, %s, %s
                FROM taxsentry.jobs
                WHERE id=%s AND lease_token=%s AND state='running' AND lease_expires_at > now()
                ON CONFLICT (job_id, name) DO UPDATE
                SET state=excluded.state,
                    checkpoint=excluded.checkpoint,
                    processed=excluded.processed,
                    total=excluded.total,
                    error=excluded.error,
                    updated_at=now()
                RETURNING *
                """,
                (
                    str(uuid.uuid4()),
                    step,
                    state,
                    _json(checkpoint),
                    processed,
                    total,
                    error[:4000],
                    job_id,
                    lease_token,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise LostLeaseError(f"Lease lost for job {job_id}")
            return _row(row)

    def complete(
        self,
        job_id: str,
        lease_token: str,
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._finish(
            job_id,
            lease_token,
            state="completed",
            result=result or {},
            error="",
            release_reason="completed",
        )

    def fail(
        self,
        job_id: str,
        lease_token: str,
        error: str,
        *,
        retryable: bool = True,
        retry_delay_seconds: int = 0,
    ) -> dict[str, Any]:
        _validate_uuid(job_id, "job_id")
        _validate_uuid(lease_token, "lease_token")
        if retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds cannot be negative")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE taxsentry.jobs
                SET state=CASE
                        WHEN %s AND attempts < max_attempts THEN 'queued'
                        ELSE 'failed'
                    END,
                    available_at=CASE
                        WHEN %s AND attempts < max_attempts
                            THEN now() + (%s * interval '1 second')
                        ELSE available_at
                    END,
                    error=%s,
                    leased_by=NULL,
                    lease_token=NULL,
                    lease_expires_at=NULL,
                    heartbeat_at=NULL,
                    updated_at=now()
                WHERE id=%s AND lease_token=%s AND state='running' AND lease_expires_at > now()
                RETURNING *
                """,
                (
                    retryable,
                    retryable,
                    retry_delay_seconds,
                    error[:4000],
                    job_id,
                    lease_token,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                raise LostLeaseError(f"Lease lost for job {job_id}")
            job = _row(row)
            reason = "retry_scheduled" if job["state"] == "queued" else "failed"
            self._release_lease(cursor, lease_token, reason)
            self._event(cursor, job_id, reason, {"attempts": job["attempts"]})
            return job

    def request_cancel(self, job_id: str) -> bool:
        _validate_uuid(job_id, "job_id")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE taxsentry.jobs
                SET cancel_requested=true,
                    state='cancelled',
                    leased_by=NULL,
                    lease_token=NULL,
                    lease_expires_at=NULL,
                    heartbeat_at=NULL,
                    updated_at=now()
                WHERE id=%s AND state IN ('queued', 'running')
                RETURNING id
                """,
                (job_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            cursor.execute(
                """
                UPDATE taxsentry.job_leases
                SET released_at=now(), release_reason='cancelled'
                WHERE job_id=%s AND released_at IS NULL
                """,
                (job_id,),
            )
            self._event(cursor, job_id, "cancelled", {})
            return True

    def cancel_requested(self, job_id: str) -> bool:
        _validate_uuid(job_id, "job_id")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT cancel_requested FROM taxsentry.jobs WHERE id=%s",
                (job_id,),
            )
            row = cursor.fetchone()
            return bool(row and _value(row, "cancel_requested", 0))

    def resume(self, job_id: str, *, reset_attempts: bool = True) -> dict[str, Any] | None:
        _validate_uuid(job_id, "job_id")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE taxsentry.jobs
                SET state='queued',
                    attempts=CASE WHEN %s THEN 0 ELSE attempts END,
                    error='',
                    cancel_requested=false,
                    available_at=now(),
                    leased_by=NULL,
                    lease_token=NULL,
                    lease_expires_at=NULL,
                    heartbeat_at=NULL,
                    updated_at=now()
                WHERE id=%s AND state IN ('failed', 'cancelled')
                RETURNING *
                """,
                (reset_attempts, job_id),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            self._event(cursor, job_id, "resumed", {"reset_attempts": reset_attempts})
            return _row(row)

    def get(self, job_id: str) -> dict[str, Any] | None:
        _validate_uuid(job_id, "job_id")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM taxsentry.jobs WHERE id=%s", (job_id,))
            row = cursor.fetchone()
            return _row(row) if row else None

    def steps(self, job_id: str) -> list[dict[str, Any]]:
        _validate_uuid(job_id, "job_id")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM taxsentry.job_steps WHERE job_id=%s ORDER BY updated_at, name",
                (job_id,),
            )
            return [_row(row) for row in cursor.fetchall()]

    def get_document(
        self,
        document_id: str,
        *,
        company_id: str,
    ) -> dict[str, Any] | None:
        _require_text(document_id, "document_id")
        _require_text(company_id, "company_id")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, company_id, sha256, raw_object_key, manifest
                FROM taxsentry.documents
                WHERE id=%s AND company_id=%s
                """,
                (document_id.strip(), company_id.strip()),
            )
            row = cursor.fetchone()
            return _row(row) if row else None

    def persist_document(
        self,
        manifest: Mapping[str, Any],
        units: Iterable[Mapping[str, Any]],
        *,
        raw_object_key: str,
        units_object_key: str,
        mime_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Persist one ingested document and its structural units idempotently."""
        company_id = str(manifest.get("company_id") or "").strip()
        case_id = str(manifest.get("case_id") or "").strip()
        source_document_id = str(manifest.get("id") or "").strip()
        sha256 = str(manifest.get("sha256") or "").lower()
        name = str(manifest.get("name") or "")
        if not company_id or not case_id or not source_document_id:
            raise ValueError("Document manifest requires id, company_id, and case_id")
        if len(sha256) != 64 or any(
            character not in "0123456789abcdef" for character in sha256
        ):
            raise ValueError("Document manifest requires a SHA-256 digest")
        if not raw_object_key or not units_object_key:
            raise ValueError("Document persistence requires object keys")
        manifest_json = json.dumps(
            dict(manifest),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO taxsentry.companies (id)
                VALUES (%s)
                ON CONFLICT (id) DO NOTHING
                """,
                (company_id,),
            )
            cursor.execute(
                """
                INSERT INTO taxsentry.cases (id, company_id, status)
                VALUES (%s, %s, 'ingested')
                ON CONFLICT (id) DO UPDATE
                SET status='ingested', updated_at=now()
                WHERE taxsentry.cases.company_id=excluded.company_id
                RETURNING id
                """,
                (case_id, company_id),
            )
            if cursor.fetchone() is None:
                raise ValueError("Case belongs to another company")
            cursor.execute(
                """
                INSERT INTO taxsentry.documents
                    (id, company_id, sha256, name, mime_type, size_bytes,
                     raw_object_key, manifest)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (company_id, sha256) DO UPDATE
                SET name=excluded.name,
                    mime_type=excluded.mime_type,
                    size_bytes=excluded.size_bytes,
                    raw_object_key=excluded.raw_object_key,
                    manifest=excluded.manifest
                RETURNING id
                """,
                (
                    source_document_id,
                    company_id,
                    sha256,
                    name,
                    mime_type,
                    max(0, int(manifest.get("size_bytes") or 0)),
                    raw_object_key,
                    manifest_json,
                ),
            )
            document_row = cursor.fetchone()
            if document_row is None:
                raise RuntimeError("Document persistence returned no document id")
            document_id = str(_value(document_row, "id", 0))
            cursor.execute(
                """
                INSERT INTO taxsentry.case_documents (case_id, document_id)
                VALUES (%s, %s)
                ON CONFLICT (case_id, document_id) DO NOTHING
                """,
                (case_id, document_id),
            )
            cursor.execute(
                "DELETE FROM taxsentry.document_units WHERE document_id=%s",
                (document_id,),
            )
            unit_sql = """
                INSERT INTO taxsentry.document_units
                    (id, document_id, company_id, kind, ordinal, locator,
                     content, structured, object_key, status, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET content=excluded.content,
                    structured=excluded.structured,
                    object_key=excluded.object_key,
                    status=excluded.status,
                    error=excluded.error
                WHERE taxsentry.document_units.company_id=excluded.company_id
                  AND taxsentry.document_units.document_id=excluded.document_id
                """
            count = 0
            batch: list[tuple[Any, ...]] = []
            for unit in units:
                structured = dict(unit.get("structured") or {})
                if unit.get("warnings"):
                    structured["_warnings"] = list(unit["warnings"])
                batch.append(
                    (
                        str(unit.get("id") or ""),
                        document_id,
                        company_id,
                        str(unit.get("kind") or "unknown"),
                        int(unit.get("ordinal") or 0),
                        str(unit.get("locator") or ""),
                        str(unit.get("text") or unit.get("content") or ""),
                        _json(structured),
                        units_object_key,
                        str(unit.get("status") or "processed"),
                        str(unit.get("error") or "")[:4000],
                    )
                )
                if len(batch) == 500:
                    cursor.executemany(unit_sql, batch)
                    count += len(batch)
                    batch.clear()
            if batch:
                cursor.executemany(unit_sql, batch)
                count += len(batch)
            return {"document_id": document_id, "unit_count": count}

    def import_legacy_job(self, legacy: Mapping[str, Any], *, company_id: str) -> bool:
        """Idempotently import one v2 SQLite job without replaying completed work."""
        _require_text(company_id, "company_id")
        company_id = company_id.strip()
        source_id = str(legacy.get("id") or uuid.uuid4())
        try:
            legacy_id = str(uuid.UUID(source_id))
        except ValueError:
            legacy_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"taxsentry-v2:{source_id}"))
        message_id = str(legacy.get("gmail_message_id") or legacy_id)
        legacy_state = str(legacy.get("state") or "queued")
        replay_blocked = legacy_state not in {"completed", "failed", "cancelled"}
        state = legacy_state if legacy_state in {"completed", "cancelled"} else "failed"
        created_at = legacy.get("created_at") or "1970-01-01T00:00:00+00:00"
        updated_at = legacy.get("updated_at") or created_at
        payload = {
            "source": "taxsentry-v2-sqlite",
            "job_type": "legacy-v2",
            "legacy_id": source_id,
            "gmail_message_id": message_id,
            "sender": str(legacy.get("sender") or ""),
            "subject": str(legacy.get("subject") or ""),
            "report_path": str(legacy.get("report_path") or ""),
            "legacy_state": legacy_state,
            "legacy_replay_blocked": replay_blocked,
        }
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO taxsentry.jobs
                    (id, company_id, idempotency_key, state, payload, attempts, error,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                ON CONFLICT (company_id, idempotency_key) DO NOTHING
                RETURNING id
                """,
                (
                    legacy_id,
                    company_id,
                    f"legacy:gmail:{message_id}",
                    state,
                    _json(payload),
                    max(0, int(legacy.get("retries") or 0)),
                    f"LegacyState:{legacy_state}" if state == "failed" else "",
                    created_at,
                    updated_at,
                ),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            self._event(cursor, legacy_id, "legacy_imported", {"legacy_state": legacy_state})
            return True

    def _finish(
        self,
        job_id: str,
        lease_token: str,
        *,
        state: str,
        result: Mapping[str, Any],
        error: str,
        release_reason: str,
    ) -> dict[str, Any]:
        _validate_uuid(job_id, "job_id")
        _validate_uuid(lease_token, "lease_token")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE taxsentry.jobs
                SET state=%s,
                    result=%s::jsonb,
                    error=%s,
                    leased_by=NULL,
                    lease_token=NULL,
                    lease_expires_at=NULL,
                    heartbeat_at=NULL,
                    updated_at=now()
                WHERE id=%s AND lease_token=%s AND state='running' AND lease_expires_at > now()
                RETURNING *
                """,
                (state, _json(result), error[:4000], job_id, lease_token),
            )
            row = cursor.fetchone()
            if row is None:
                raise LostLeaseError(f"Lease lost for job {job_id}")
            self._release_lease(cursor, lease_token, release_reason)
            self._event(cursor, job_id, state, {})
            return _row(row)

    @staticmethod
    def _event(cursor, job_id: str, kind: str, payload: Mapping[str, Any]) -> None:
        cursor.execute(
            """
            INSERT INTO taxsentry.job_events (id, job_id, kind, payload)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (str(uuid.uuid4()), job_id, kind, _json(payload)),
        )

    @staticmethod
    def _release_lease(cursor, lease_token: str, reason: str) -> None:
        cursor.execute(
            """
            UPDATE taxsentry.job_leases
            SET released_at=now(), release_reason=%s
            WHERE id=%s AND released_at IS NULL
            """,
            (reason, lease_token),
        )


def _json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(dict(value), ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Queue payload must be JSON serializable") from exc


def _row(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    raise TypeError("PostgreSQL connection must use mapping rows")


def _value(row: Any, key: str, index: int) -> Any:
    return row[key] if isinstance(row, Mapping) else row[index]


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError(f"{name} must be non-empty and at most 255 characters")


def _validate_uuid(value: str, name: str) -> None:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def _validate_lease_seconds(value: int) -> None:
    if not isinstance(value, int) or not 5 <= value <= 3600:
        raise ValueError("lease_seconds must be between 5 and 3600")


JobQueue = PostgresJobQueue
