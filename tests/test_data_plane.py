from __future__ import annotations

import asyncio
import hashlib
import io
import json
import sqlite3
import uuid

import pytest

import taxsentry.data_plane.distributed_documents as distributed_documents
from taxsentry.data_plane import (
    DistributedDocumentError,
    DistributedDocumentService,
    DocumentJobCancelled,
    DocumentJobFailed,
    DocumentJobTimeout,
    JobQueue,
    job_queue_from_settings,
    object_store_from_settings,
)
from taxsentry.data_plane.document_worker import process_document_job
from taxsentry.data_plane.migration import (
    SQLITE_SNAPSHOT_NAME,
    _ImportOutcome,
    _LegacyPostgresImporter,
    _migrate_connection,
    export_sqlite_snapshot,
    migrate_sqlite_database,
    migrate_sqlite_jobs,
)
from taxsentry.data_plane.object_store import LocalObjectStore, S3ObjectStore
from taxsentry.data_plane.queue import (
    DataPlaneDependencyError,
    LostLeaseError,
    PostgresJobQueue,
)
from taxsentry.data_plane.worker import LeaseWorker, _postgres_dsn_from_env
from taxsentry.documents import (
    DOCUMENT_EXTRACTION_SCHEMA_VERSION,
    CoverageReport,
    DocumentManifest,
    DocumentService,
)

_DISTRIBUTED_PDF = b"%PDF-1.7\nfixture"


class _ScriptedCursor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self.current = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        self.current = self.responses.pop(0) if self.responses else []
        return self

    def executemany(self, sql, params):
        self.executed.append((" ".join(sql.split()), list(params)))
        self.current = self.responses.pop(0) if self.responses else []
        return self

    def fetchone(self):
        return self.current[0] if self.current else None

    def fetchall(self):
        return list(self.current)


class _ScriptedConnection:
    def __init__(self, responses):
        self.cursor_value = _ScriptedCursor(responses)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_value


def test_postgres_claim_uses_skip_locked_and_token_bound_lease():
    job_id, token_time = str(uuid.uuid4()), "2026-07-26T00:01:00+00:00"
    connection = _ScriptedConnection(
        [[{
            "id": job_id,
            "state": "running",
            "attempts": 1,
            "lease_token": "set-by-query",
            "lease_expires_at": token_time,
        }]]
    )
    queue = PostgresJobQueue(connect=lambda: connection)

    claimed = queue.claim("worker-1", lease_seconds=30)

    assert claimed and claimed["id"] == job_id
    claim_sql, claim_params = connection.cursor_value.executed[0]
    assert "FOR UPDATE SKIP LOCKED" in claim_sql
    assert "attempts < max_attempts" in claim_sql
    assert claim_params[0] == "worker-1" and uuid.UUID(claim_params[1])
    assert "release_reason='expired'" in connection.cursor_value.executed[1][0]
    lease_sql, lease_params = connection.cursor_value.executed[2]
    assert "INSERT INTO taxsentry.job_leases" in lease_sql
    assert lease_params[0] == claim_params[1]


def test_job_queue_alias_and_document_persistence_are_public_and_idempotent():
    assert JobQueue is PostgresJobQueue
    connection = _ScriptedConnection(
        [
            [],
            [{"id": "case-1"}],
            [{"id": "document-from-digest"}],
            [],
            [],
        ]
    )
    queue = JobQueue(connect=lambda: connection)
    manifest = {
        "id": "document-source",
        "company_id": "company-1",
        "case_id": "case-1",
        "name": "ledger.xlsx",
        "sha256": "a" * 64,
        "size_bytes": 128,
    }
    units = [
        {
            "id": "unit-1",
            "kind": "sheet",
            "ordinal": 1,
            "locator": "sheet=Summary",
            "text": "Revenue",
            "structured": {"rows": 1},
            "warnings": ["cached formula missing"],
        },
        {
            "id": "unit-2",
            "kind": "sheet",
            "ordinal": 2,
            "locator": "sheet=Tax",
            "status": "failed",
            "error": "corrupt cell",
        },
    ]

    result = queue.persist_document(
        manifest,
        units,
        raw_object_key="incoming/ledger.xlsx",
        units_object_key="jobs/job-1/units.jsonl",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert result == {"document_id": "document-from-digest", "unit_count": 2}
    case_sql = connection.cursor_value.executed[1][0]
    assert "WHERE taxsentry.cases.company_id=excluded.company_id" in case_sql
    unit_sql, unit_params = connection.cursor_value.executed[-1]
    assert "ON CONFLICT (id) DO UPDATE" in unit_sql
    assert len(unit_params) == 2
    assert unit_params[0][1:3] == ("document-from-digest", "company-1")
    assert json.loads(unit_params[0][7])["_warnings"] == ["cached formula missing"]


def test_checkpoint_rejects_progress_and_lost_lease():
    queue = PostgresJobQueue(connect=lambda: _ScriptedConnection([[]]))
    with pytest.raises(ValueError, match="progress"):
        queue.checkpoint(
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            "extract",
            {},
            processed=2,
            total=1,
        )
    with pytest.raises(LostLeaseError):
        queue.checkpoint(
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            "extract",
            {},
            processed=1,
            total=1,
        )


def test_queue_heartbeat_retry_cancel_and_resume_are_lease_safe():
    job_id, lease_token = str(uuid.uuid4()), str(uuid.uuid4())
    heartbeat_connection = _ScriptedConnection(
        [[{"lease_expires_at": "later"}]]
    )
    queue = PostgresJobQueue(connect=lambda: heartbeat_connection)
    assert queue.heartbeat(job_id, lease_token, lease_seconds=30)
    heartbeat_sql, heartbeat_params = heartbeat_connection.cursor_value.executed[0]
    assert "lease_token=%s" in heartbeat_sql and "lease_expires_at > now()" in heartbeat_sql
    assert heartbeat_params[1:] == (job_id, lease_token)

    retry_connection = _ScriptedConnection(
        [[{"id": job_id, "state": "queued", "attempts": 1}]]
    )
    retried = PostgresJobQueue(connect=lambda: retry_connection).fail(
        job_id,
        lease_token,
        "temporary",
        retry_delay_seconds=5,
    )
    retry_sql = retry_connection.cursor_value.executed[0][0]
    assert retried["state"] == "queued"
    assert "attempts < max_attempts" in retry_sql
    assert "lease_token=%s" in retry_sql and "lease_expires_at > now()" in retry_sql

    cancel_connection = _ScriptedConnection([[{"id": job_id}]])
    assert PostgresJobQueue(connect=lambda: cancel_connection).request_cancel(job_id)
    assert "state='cancelled'" in cancel_connection.cursor_value.executed[0][0]

    resume_connection = _ScriptedConnection(
        [[{"id": job_id, "state": "queued", "attempts": 0}]]
    )
    resumed = PostgresJobQueue(connect=lambda: resume_connection).resume(job_id)
    assert resumed and resumed["state"] == "queued"
    assert "state IN ('failed', 'cancelled')" in resume_connection.cursor_value.executed[0][0]


def test_postgres_dependency_failure_is_actionable(monkeypatch):
    queue = PostgresJobQueue("postgresql://localhost/taxsentry")
    original_import = __import__

    def blocked_import(name, *args, **kwargs):
        if name == "psycopg":
            raise ModuleNotFoundError(name)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", blocked_import)
    with pytest.raises(DataPlaneDependencyError, match=r"psycopg\[binary\]==3\.3\.4"):
        queue.get(str(uuid.uuid4()))


def test_local_object_store_round_trip_and_blocks_traversal(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    source = tmp_path / "large.bin"
    source.write_bytes(b"taxsentry" * 200_000)

    stored = store.put_file("company/case/report.bin", source)
    destination = tmp_path / "downloaded.bin"
    downloaded = store.download(stored.key, destination)

    assert stored.size == source.stat().st_size
    assert stored.sha256 == downloaded.sha256
    assert store.get_bytes(stored.key) == source.read_bytes()
    with pytest.raises(ValueError):
        store.put_bytes("../escape", b"no")
    with pytest.raises(ValueError):
        store.put_bytes("C:/escape", b"no")


class _FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body, Metadata, **kwargs):
        self.objects[(Bucket, Key)] = (bytes(Body), Metadata)
        return {"ETag": '"etag"'}

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)][0])}

    def download_file(self, bucket, key, destination):
        data, _ = self.objects[(bucket, key)]
        with open(destination, "wb") as stream:
            stream.write(data)

    def head_object(self, *, Bucket, Key):
        data, metadata = self.objects[(Bucket, Key)]
        return {"ContentLength": len(data), "Metadata": metadata, "ETag": '"etag"'}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


def test_s3_object_store_works_with_injected_minio_client():
    client = _FakeS3()
    store = S3ObjectStore(bucket="taxsentry", client=client)

    stored = store.put_bytes("company/report.pdf", b"%PDF-1.7")

    assert stored.etag == "etag"
    assert store.exists(stored.key)
    assert store.get_bytes(stored.key) == b"%PDF-1.7"
    store.delete(stored.key)
    assert not client.objects


def test_sqlite_export_is_consistent_and_hashed(tmp_path):
    database = tmp_path / "v2.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, payload BLOB)")
        connection.execute("INSERT INTO jobs VALUES ('job-1', ?)", (b"\x00\x01",))
        connection.execute('CREATE TABLE "../escape" (value TEXT)')
        connection.execute('INSERT INTO "../escape" VALUES ("blocked")')
    destination = tmp_path / "export"

    manifest_path = export_sqlite_snapshot(database, destination)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    exported = json.loads((destination / "jobs.jsonl").read_text(encoding="utf-8"))
    snapshot = destination / SQLITE_SNAPSHOT_NAME

    assert manifest["tables"]["jobs"]["rows"] == 1
    assert len(manifest["tables"]["jobs"]["sha256"]) == 64
    assert manifest["snapshot_file"] == SQLITE_SNAPSHOT_NAME
    assert manifest["snapshot_sha256"] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    with sqlite3.connect(snapshot) as connection:
        assert connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    assert manifest["tables"]["../escape"]["file"].startswith("table-")
    assert not (tmp_path / "escape.jsonl").exists()
    assert exported == {"id": "job-1", "payload": {"$base64": "AAE="}}


def test_sqlite_job_migration_is_idempotent(tmp_path):
    database = tmp_path / "v2.db"
    job_id = str(uuid.uuid4())
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, gmail_message_id TEXT, sender TEXT, "
            "subject TEXT, state TEXT, retries INTEGER, error TEXT, report_path TEXT, "
            "created_at TEXT, updated_at TEXT)"
        )
        connection.execute(
            "INSERT INTO jobs VALUES (?, 'gmail-1', 'a@example.com', 'Report', "
            "'completed', 0, '', 'report.pdf', '2026-07-26', '2026-07-26')",
            (job_id,),
        )

    class Queue:
        def __init__(self):
            self.seen = set()
            self.rows = []

        def import_legacy_job(self, row, *, company_id):
            key = (company_id, row["gmail_message_id"])
            if key in self.seen:
                return False
            self.seen.add(key)
            self.rows.append(row)
            return True

    queue = Queue()
    assert migrate_sqlite_jobs(database, queue).imported == 1
    second = migrate_sqlite_jobs(database, queue)
    assert second.imported == 0 and second.skipped == 1


def test_legacy_inflight_job_is_imported_as_non_claimable_review_state():
    legacy_id = str(uuid.uuid4())
    connection = _ScriptedConnection([[{"id": legacy_id}], []])
    queue = PostgresJobQueue(connect=lambda: connection)

    assert queue.import_legacy_job(
        {
            "id": legacy_id,
            "gmail_message_id": "gmail-1",
            "state": "extracting",
            "retries": 1,
        },
        company_id="company-a",
    )

    params = connection.cursor_value.executed[0][1]
    payload = json.loads(params[4])
    assert params[3] == "failed"
    assert params[6] == "LegacyState:extracting"
    assert payload["job_type"] == "legacy-v2"
    assert payload["legacy_replay_blocked"] is True


def test_full_sqlite_migration_inventory_is_scoped_reported_and_idempotent(tmp_path):
    database = tmp_path / "v2.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE companies (id TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, company_id TEXT, created_at TEXT
            );
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, company_id TEXT, created_at TEXT
            );
            CREATE TABLE messages (
                id TEXT PRIMARY KEY, session_id TEXT, company_id TEXT, created_at TEXT
            );
            CREATE TABLE reports (
                id TEXT PRIMARY KEY, job_id TEXT, created_at TEXT
            );
            CREATE TABLE events (
                id TEXT PRIMARY KEY, job_id TEXT, created_at TEXT
            );
            CREATE TABLE deliveries (
                id TEXT PRIMARY KEY, job_id TEXT, created_at TEXT
            );
            CREATE TABLE attachments (id TEXT PRIMARY KEY, job_id TEXT);
            INSERT INTO companies VALUES ('company-a', 'A');
            INSERT INTO jobs VALUES ('job-1', 'company-a', '2026-01-01');
            INSERT INTO sessions VALUES ('session-1', 'company-a', '2026-01-01');
            INSERT INTO messages VALUES
                ('message-1', 'session-1', 'company-a', '2026-01-01'),
                ('message-orphan', 'missing-session', 'company-a', '2026-01-01'),
                ('message-wrong-company', 'session-1', 'company-b', '2026-01-01');
            INSERT INTO reports VALUES
                ('report-1', 'job-1', '2026-01-01'),
                ('report-orphan', 'missing-job', '2026-01-01');
            INSERT INTO events VALUES ('event-1', 'job-1', '2026-01-01');
            INSERT INTO deliveries VALUES
                ('delivery-1', 'job-1', '2026-01-01'),
                ('delivery-orphan', 'missing-job', '2026-01-01');
            INSERT INTO attachments VALUES
                ('attachment-1', 'job-1'),
                ('attachment-orphan', 'missing-job');
            """
        )
        connection.row_factory = sqlite3.Row

        class Importer:
            def __init__(self):
                self.seen = set()

            def outcome(self, table, key, *, object_ref=False):
                identity = (table, key)
                if identity in self.seen:
                    return _ImportOutcome("skipped")
                self.seen.add(identity)
                return _ImportOutcome("imported", object_ref)

            def company(self, company_id, row):
                return self.outcome("companies", company_id)

            def job(self, row, company_id):
                return self.outcome("jobs", row["id"])

            def session(self, row, company_id):
                return self.outcome("sessions", row["id"])

            def message(self, row, company_id):
                return self.outcome("messages", row["id"])

            def report(self, row, company_id):
                return self.outcome("reports", row["id"], object_ref=True)

            def event(self, row, company_id):
                return self.outcome("events", row["id"])

            def delivery(self, row, company_id):
                return self.outcome("deliveries", row["id"])

            def attachment(self, row, company_id):
                return self.outcome("attachments", row["id"], object_ref=True)

        importer = Importer()
        first = _migrate_connection(connection, importer, "default")
        second = _migrate_connection(connection, importer, "default")

    assert first.imported == 9
    assert first.conflicts == 5
    assert first.object_refs == 2
    assert first.tables["companies"].imported == 2
    assert first.tables["messages"].conflicts == 2
    assert first.tables["reports"].conflicts == 1
    assert first.tables["deliveries"].conflicts == 1
    assert first.tables["attachments"].conflicts == 1
    assert second.imported == 0
    assert second.skipped == 9
    assert second.conflicts == 5
    assert second.object_refs == 0


def test_public_sqlite_migration_imports_v2_rows_and_object_references(tmp_path):
    database = tmp_path / "v2.db"
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    attachment = downloads / "ledger.xlsx"
    report_pdf = downloads / "report.pdf"
    attachment.write_bytes(b"legacy workbook")
    report_pdf.write_bytes(b"%PDF-1.7 legacy")
    attachment_sha256 = hashlib.sha256(attachment.read_bytes()).hexdigest()
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE jobs (
              id TEXT PRIMARY KEY, gmail_message_id TEXT, sender TEXT, subject TEXT,
              state TEXT, retries INTEGER, error TEXT, report_path TEXT,
              created_at TEXT, updated_at TEXT
            );
            CREATE TABLE attachments (
              id TEXT PRIMARY KEY, job_id TEXT, name TEXT, path TEXT,
              sha256 TEXT, mime_type TEXT
            );
            CREATE TABLE reports (
              id TEXT PRIMARY KEY, job_id TEXT, payload TEXT, confidence REAL,
              pdf_path TEXT, created_at TEXT
            );
            CREATE TABLE deliveries (
              id TEXT PRIMARY KEY, job_id TEXT, channel TEXT, external_id TEXT,
              status TEXT, created_at TEXT
            );
            CREATE TABLE sessions (
              id TEXT PRIMARY KEY, provider TEXT, platform TEXT, company_id TEXT,
              model TEXT, system_prompt TEXT, system_prompt_hash TEXT, summary TEXT,
              provider_thread_id TEXT, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE messages (
              id TEXT PRIMARY KEY, session_id TEXT, company_id TEXT, role TEXT,
              content TEXT, source TEXT, trusted INTEGER, pinned INTEGER,
              expires_at TEXT, created_at TEXT
            );
            CREATE TABLE events (
              id TEXT PRIMARY KEY, job_id TEXT, kind TEXT, payload TEXT, created_at TEXT
            );
            INSERT INTO jobs VALUES (
              'job-1', 'gmail-1', 'a@example.com', 'Tax report', 'completed',
              0, '', 'report.pdf', '2026-01-01', '2026-01-02'
            );
            INSERT INTO attachments VALUES (
              'attachment-1', 'job-1', 'ledger.xlsx', 'downloads/ledger.xlsx',
              '__ATTACHMENT_SHA__',
              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            );
            INSERT INTO reports VALUES (
              'report-1', 'job-1', '{"revenue":100}', 0.9,
              'downloads/report.pdf', '2026-01-02'
            );
            INSERT INTO deliveries VALUES (
              'delivery-1', 'job-1', 'gmail', 'message-1', 'sent', '2026-01-02'
            );
            INSERT INTO sessions VALUES (
              'session-1', 'openai', 'terminal', 'default', 'gpt', 'prompt', '',
              'summary', '', '2026-01-01', '2026-01-02'
            );
            INSERT INTO messages VALUES (
              'message-1', 'session-1', 'default', 'user', 'hello', 'terminal',
              1, 0, '', '2026-01-01'
            );
            INSERT INTO events VALUES (
              'event-1', 'job-1', 'state', '{"state":"completed"}', '2026-01-02'
            );
            """.replace("__ATTACHMENT_SHA__", attachment_sha256)
        )
    source_bytes = database.read_bytes()

    class Cursor:
        def __init__(self, inserted, document_digests):
            self.inserted = inserted
            self.document_digests = document_digests
            self.current = []

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            self.current = []
            if normalized.startswith("SELECT 1 FROM taxsentry.artifacts"):
                if ("artifacts", params[0]) in self.inserted:
                    self.current = [{"exists": 1}]
                return self
            if normalized.startswith("SELECT 1 FROM taxsentry.documents"):
                if (params[0], params[1]) in self.document_digests:
                    self.current = [{"exists": 1}]
                return self
            if "RETURNING id" not in normalized:
                return self
            table = next(
                name
                for name in (
                    "companies",
                    "sessions",
                    "messages",
                    "artifacts",
                    "job_events",
                    "deliveries",
                    "documents",
                )
                if f"INSERT INTO taxsentry.{name}" in normalized
            )
            identity = (table, params[0])
            if identity not in self.inserted:
                self.inserted.add(identity)
                self.current = [{"id": params[0]}]
                if table == "documents":
                    self.document_digests.add((params[1], params[2]))
            return self

        def fetchone(self):
            return self.current[0] if self.current else None

    class Connection:
        def __init__(self):
            self.inserted = set()
            self.document_digests = set()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def cursor(self):
            return Cursor(self.inserted, self.document_digests)

    class Queue:
        def __init__(self):
            self.connection = Connection()
            self.jobs = set()

        def _connect(self):
            return self.connection

        def import_legacy_job(self, row, *, company_id):
            identity = (company_id, row["id"])
            if identity in self.jobs:
                return False
            self.jobs.add(identity)
            return True

    class CountingObjectStore(LocalObjectStore):
        writes = 0

        def put_bytes(self, key, data):
            self.writes += 1
            return super().put_bytes(key, data)

        def put_file(self, key, source, *, sha256=None):
            self.writes += 1
            return super().put_file(key, source, sha256=sha256)

    queue = Queue()
    object_store = CountingObjectStore(tmp_path / "objects")
    snapshot = tmp_path / "backup" / SQLITE_SNAPSHOT_NAME
    snapshot.parent.mkdir()
    snapshot.write_bytes(database.read_bytes())
    first = migrate_sqlite_database(
        snapshot,
        queue,
        object_store=object_store,
        legacy_source_root=database.parent,
    )
    second = migrate_sqlite_database(
        snapshot,
        queue,
        object_store=object_store,
        legacy_source_root=database.parent,
    )

    assert first.imported == 8
    assert first.object_refs == 2
    assert first.conflicts == 0
    assert second.imported == 0
    assert second.skipped == 8
    assert second.object_refs == 0
    assert database.read_bytes() == source_bytes
    assert object_store.writes == 2
    assert len([path for path in (tmp_path / "objects").rglob("*") if path.is_file()]) == 2
    assert all(
        len(path.relative_to(tmp_path / "objects").parts) >= 4
        for path in (tmp_path / "objects").rglob("*")
        if path.is_file()
    )


def test_legacy_attachment_rejects_path_escape_and_sha_mismatch(tmp_path):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    evidence = downloads / "evidence.txt"
    evidence.write_bytes(b"approved")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    objects = LocalObjectStore(tmp_path / "objects")
    importer = _LegacyPostgresImporter(object(), objects, tmp_path, (downloads,))

    with pytest.raises(ValueError, match="outside approved roots"):
        importer.attachment(
            {
                "id": "outside",
                "job_id": "job",
                "path": str(outside),
                "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
            },
            "company-a",
        )
    assert (
        importer.attachment(
            {
                "id": "bad-hash",
                "job_id": "job",
                "path": str(evidence),
                "sha256": "0" * 64,
            },
            "company-a",
        ).status
        == "conflict"
    )
    assert not [path for path in (tmp_path / "objects").rglob("*") if path.is_file()]


def test_document_worker_uploads_portable_manifest_and_persists_units(tmp_path):
    object_store = LocalObjectStore(tmp_path / "objects")
    raw = b"fixture"
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    company_namespace = hashlib.sha256(b"company-1").hexdigest()[:16]
    object_key = (
        f"documents/raw/{company_namespace}/{raw_sha256}.xlsx"
    )
    object_store.put_bytes(object_key, raw)
    request_digest = "c" * 64
    result_prefix = f"documents/results/{request_digest}"
    units_path = tmp_path / "units.jsonl"
    units_path.write_text(
        json.dumps(
            {
                "id": "unit-1",
                "document_id": "document-1",
                "kind": "sheet",
                "ordinal": 1,
                "locator": "sheet=Summary",
                "text": "Revenue 100",
                "structured": {"rows": 1},
                "status": "processed",
                "error": "",
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    analysis_path = tmp_path / "analysis.json"
    analysis_path.write_text(
        json.dumps(
            {
                "data": {
                    "canonical_metrics": {
                        "revenue": {"value": 100, "source_sheet": "Summary"}
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manifest = DocumentManifest(
        id="document-1",
        company_id="company-1",
        case_id="case-1",
        name="ledger.xlsx",
        suffix=".xlsx",
        sha256=raw_sha256,
        size_bytes=7,
        source="fixture",
        raw_uri="local",
        units_uri=str(units_path),
        created_at="2026-07-26T00:00:00+00:00",
        coverage=CoverageReport(total=1, processed=1, failed=0),
        metadata={"analysis_uri": str(analysis_path)},
    )

    class Service:
        def ingest_sync(self, **kwargs):
            assert kwargs["path"].name == "ledger.xlsx"
            return manifest

    class Context:
        id = "job-1"
        job = {
            "company_id": "company-1",
            "case_id": "case-1",
            "payload": {
                "object_key": object_key,
                "company_id": "company-1",
                "case_id": "case-1",
                "name": "ledger.xlsx",
                "sha256": raw_sha256,
                "request_digest": request_digest,
                "result_prefix": result_prefix,
                "extraction": {
                    "schema_version": DOCUMENT_EXTRACTION_SCHEMA_VERSION,
                    "excel_rows_per_unit": 250,
                },
            },
        }

        def __init__(self):
            self.checkpoints = []
            self.persisted = None

        def checkpoint(self, step, value, **progress):
            self.checkpoints.append((step, value, progress))

        def cancelled(self):
            return False

        def persist_document(self, portable_manifest, units, **keys):
            self.persisted = (portable_manifest, list(units), keys)
            return {"document_id": "document-1", "unit_count": 1}

    context = Context()
    result = process_document_job(
        context,
        object_store=object_store,
        work_root=tmp_path / "work",
        document_service=Service(),
    )

    assert result["document_id"] == "document-1"
    assert result["raw_sha256"] == raw_sha256
    assert result["manifest_sha256"]
    assert result["units_sha256"]
    assert result["analysis_sha256"]
    assert [item[0] for item in context.checkpoints] == [
        "download",
        "extract",
        "persist",
        "result",
    ]
    portable, units, keys = context.persisted
    assert portable["raw_uri"] == object_key
    assert portable["units_uri"] == keys["units_object_key"]
    assert portable["metadata"]["manifest_sha256"] == result["manifest_sha256"]
    assert units[0]["locator"] == "sheet=Summary"
    saved_manifest = json.loads(object_store.get_bytes(result["manifest_key"]))
    assert saved_manifest["units_uri"] == result["units_key"]
    assert (
        json.loads(object_store.get_bytes(result["analysis_key"]))["data"][
            "canonical_metrics"
        ]["revenue"]["value"]
        == 100
    )
    assert keys["mime_type"].endswith("spreadsheetml.sheet")

    completed = result
    context.checkpoints.clear()
    context.steps = lambda: [
        {
            "name": "result",
            "state": "completed",
            "checkpoint": completed,
        }
    ]

    class MustNotExtract:
        def ingest_sync(self, **kwargs):
            raise AssertionError("completed checkpoint must be resumed")

    assert process_document_job(
        context,
        object_store=object_store,
        work_root=tmp_path / "restart",
        document_service=MustNotExtract(),
    ) == completed
    assert context.checkpoints == []


def _seed_distributed_result(store, *, excel_rows_per_unit=250):
    raw_sha256 = hashlib.sha256(_DISTRIBUTED_PDF).hexdigest()
    extraction = {
        "schema_version": DOCUMENT_EXTRACTION_SCHEMA_VERSION,
        "excel_rows_per_unit": excel_rows_per_unit,
    }
    request_digest = hashlib.sha256(
        json.dumps(
            {
                "company_id": "company-1",
                "case_id": "case-1",
                "sha256": raw_sha256,
                "languages": ["vie", "eng"],
                "extraction": extraction,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    result_prefix = f"documents/results/{request_digest}"
    manifest_key = f"{result_prefix}/manifest.json"
    units_key = f"{result_prefix}/units.jsonl"
    analysis_key = f"{result_prefix}/analysis.json"
    raw_key = (
        f"documents/raw/{hashlib.sha256(b'company-1').hexdigest()[:16]}/"
        f"{raw_sha256}.pdf"
    )
    unit = {
        "id": "unit-1",
        "document_id": "document-1",
        "kind": "page",
        "ordinal": 1,
        "locator": "page=1",
        "text": "Revenue 100",
        "structured": {},
        "status": "processed",
        "error": "",
        "warnings": [],
    }
    units_object = store.put_bytes(
        units_key,
        (json.dumps(unit) + "\n").encode(),
    )
    analysis_object = store.put_bytes(
        analysis_key,
        json.dumps(
            {
                "data": {
                    "canonical_metrics": {
                        "revenue": {"value": 100, "source_sheet": "Summary"}
                    }
                }
            }
        ).encode(),
    )
    manifest = {
        "id": "document-1",
        "company_id": "company-1",
        "case_id": "case-1",
        "name": "ledger.pdf",
        "suffix": ".pdf",
        "sha256": raw_sha256,
        "size_bytes": 18,
        "source": "pdf",
        "raw_uri": raw_key,
        "units_uri": units_key,
        "created_at": "2026-07-26T00:00:00+00:00",
        "coverage": {
            "total": 1,
            "processed": 1,
            "failed": 0,
            "skipped": 0,
            "failed_units": [],
            "warnings": [],
        },
        "metadata": {
            "result_prefix": result_prefix,
            "units_object_key": units_key,
            "units_sha256": units_object.sha256,
            "analysis_object_key": analysis_key,
            "analysis_sha256": analysis_object.sha256,
            "extraction": extraction,
        },
    }
    manifest_object = store.put_bytes(
        manifest_key,
        (json.dumps(manifest) + "\n").encode(),
    )
    result = {
        "document_id": "document-1",
        "company_id": "company-1",
        "case_id": "case-1",
        "raw_key": raw_key,
        "raw_sha256": raw_sha256,
        "manifest_key": manifest_key,
        "manifest_sha256": manifest_object.sha256,
        "units_key": units_key,
        "units_sha256": units_object.sha256,
        "analysis_key": analysis_key,
        "analysis_sha256": analysis_object.sha256,
    }
    database_manifest = {
        **manifest,
        "metadata": {
            **manifest["metadata"],
            "manifest_object_key": manifest_key,
            "manifest_sha256": manifest_object.sha256,
        },
    }
    return result, database_manifest


class _CoordinatorQueue:
    def __init__(
        self,
        *,
        initial_state="completed",
        poll_states=(),
        result=None,
        documents=None,
    ):
        self.initial_state = initial_state
        self.poll_states = list(poll_states)
        self.result = result or {}
        self.enqueue_calls = []
        self.resume_calls = []
        self.cancel_calls = []
        self.document_calls = []
        self.documents = documents or {}
        self.get_calls = 0

    def _job(self, state):
        return {
            "id": "job-1",
            "state": state,
            "result": self.result if state == "completed" else {},
        }

    def enqueue(self, **kwargs):
        self.enqueue_calls.append(kwargs)
        return self._job(self.initial_state)

    def get(self, job_id):
        self.get_calls += 1
        state = self.poll_states.pop(0) if self.poll_states else "queued"
        return self._job(state)

    def resume(self, job_id):
        self.resume_calls.append(job_id)
        return self._job("queued")

    def request_cancel(self, job_id):
        self.cancel_calls.append(job_id)
        return True

    def get_document(self, document_id, *, company_id):
        self.document_calls.append((document_id, company_id))
        return self.documents.get((company_id, document_id))


def test_distributed_document_service_is_idempotent_and_materializes_for_query(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    result, _ = _seed_distributed_result(store)
    queue = _CoordinatorQueue(result=result)
    local = DocumentService(tmp_path / "index")
    source = tmp_path / "ledger.pdf"
    source.write_bytes(_DISTRIBUTED_PDF)
    service = DistributedDocumentService(
        queue=queue,
        object_store=store,
        local_service=local,
        sleep=lambda _: None,
    )

    first = service.ingest_sync(
        path=source,
        company_id="company-1",
        case_id="case-1",
    )
    second = service.ingest_sync(
        path=source,
        company_id="company-1",
        case_id="case-1",
    )

    assert first.id == second.id == "document-1"
    assert len(queue.enqueue_calls) == 2
    assert (
        queue.enqueue_calls[0]["idempotency_key"]
        == queue.enqueue_calls[1]["idempotency_key"]
    )
    assert queue.enqueue_calls[0]["payload"]["name"] == "ledger.pdf"
    assert service.get_manifest(
        "document-1",
        company_id="company-1",
    ).units_uri.endswith("units.jsonl")
    assert (
        service.analysis_content(
            "document-1",
            company_id="company-1",
        )["data"]["canonical_metrics"]["revenue"]["value"]
        == 100
    )
    assert (
        next(service.iter_units("document-1", company_id="company-1")).locator
        == "page=1"
    )
    assert "Revenue 100" in next(
        service.prompt_partitions(
            ["document-1"],
            company_id="company-1",
        )
    )
    assert service.query_sync(
        document_id="document-1",
        company_id="company-1",
        query="revenue",
    )[0].locator == "page=1"
    assert asyncio.run(
        service.query(
            document_id="document-1",
            company_id="company-1",
            query="revenue",
        )
    )[0].locator == "page=1"
    assert asyncio.run(
        service.coverage("document-1", company_id="company-1")
    ).complete
    with pytest.raises(KeyError):
        service.get_manifest("document-1", company_id="company-2")


def test_distributed_document_service_rejects_tampered_result_object(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    result, _ = _seed_distributed_result(store)
    store.put_bytes(result["units_key"], b"tampered")
    queue = _CoordinatorQueue(result=result)
    source = tmp_path / "ledger.pdf"
    source.write_bytes(_DISTRIBUTED_PDF)
    service = DistributedDocumentService(
        queue=queue,
        object_store=store,
        local_service=DocumentService(tmp_path / "index"),
        sleep=lambda _: None,
    )

    with pytest.raises(DistributedDocumentError, match="units SHA-256"):
        service.ingest_sync(
            path=source,
            company_id="company-1",
            case_id="case-1",
        )


@pytest.mark.parametrize("initial_state", ["failed", "cancelled"])
def test_distributed_document_service_resumes_existing_terminal_job(
    tmp_path,
    initial_state,
):
    store = LocalObjectStore(tmp_path / "objects")
    result, _ = _seed_distributed_result(store)
    queue = _CoordinatorQueue(
        initial_state=initial_state,
        poll_states=["completed"],
        result=result,
    )
    source = tmp_path / "ledger.pdf"
    source.write_bytes(_DISTRIBUTED_PDF)
    service = DistributedDocumentService(
        queue=queue,
        object_store=store,
        local_service=DocumentService(tmp_path / "index"),
        sleep=lambda _: None,
    )

    manifest = service.ingest_sync(
        path=source,
        company_id="company-1",
        case_id="case-1",
    )

    assert manifest.id == "document-1"
    assert queue.resume_calls == ["job-1"]


@pytest.mark.parametrize(
    ("terminal_state", "error_type"),
    [
        ("failed", DocumentJobFailed),
        ("cancelled", DocumentJobCancelled),
    ],
)
def test_distributed_document_service_surfaces_terminal_poll_state(
    tmp_path,
    terminal_state,
    error_type,
):
    store = LocalObjectStore(tmp_path / "objects")
    queue = _CoordinatorQueue(
        initial_state="queued",
        poll_states=[terminal_state],
    )
    source = tmp_path / "ledger.pdf"
    source.write_bytes(_DISTRIBUTED_PDF)
    service = DistributedDocumentService(
        queue=queue,
        object_store=store,
        local_service=DocumentService(tmp_path / "index"),
        sleep=lambda _: None,
    )

    with pytest.raises(error_type):
        service.ingest_sync(
            path=source,
            company_id="company-1",
            case_id="case-1",
        )


def test_distributed_document_service_has_bounded_timeout_and_cancel(tmp_path):
    store = LocalObjectStore(tmp_path / "objects")
    queue = _CoordinatorQueue(initial_state="queued")
    source = tmp_path / "ledger.pdf"
    source.write_bytes(_DISTRIBUTED_PDF)
    clock = [0.0]

    def advance(seconds):
        clock[0] += seconds

    service = DistributedDocumentService(
        queue=queue,
        object_store=store,
        local_service=DocumentService(tmp_path / "index"),
        poll_seconds=0.1,
        timeout_seconds=0.25,
        sleep=advance,
        monotonic=lambda: clock[0],
    )

    with pytest.raises(DocumentJobTimeout):
        service.ingest_sync(
            path=source,
            company_id="company-1",
            case_id="case-1",
        )
    assert queue.get_calls == 3
    assert queue.cancel_calls == ["job-1"]
    assert service.cancel("job-1")
    assert queue.cancel_calls == ["job-1", "job-1"]


def test_distributed_document_service_cancels_every_active_case_job(tmp_path):
    queue = _CoordinatorQueue(initial_state="queued")
    service = DistributedDocumentService(
        queue=queue,
        object_store=LocalObjectStore(tmp_path / "objects"),
        local_service=DocumentService(tmp_path / "index"),
    )
    service._track_job("company-1", "case-1", "job-1")
    service._track_job("company-1", "case-1", "job-2")

    assert service.cancel_case("case-1", company_id="company-1")
    assert queue.cancel_calls == ["job-1", "job-2"]
    assert not service.cancel_case("case-1", company_id="company-2")


def test_data_plane_factories_use_keyring_and_require_explicit_insecure_http(
    monkeypatch,
):
    settings = {
        "data_plane": {
            "object_store": {
                "kind": "s3",
                "endpoint_url": "http://minio:9000",
                "bucket": "taxsentry",
            }
        }
    }
    secrets = {
        "data-plane:s3-access-key": "access",
        "data-plane:s3-secret-key": "secret",
        "data-plane:postgres-password": "p@ss word",
    }
    with pytest.raises(ValueError, match="HTTP object storage"):
        object_store_from_settings(
            settings,
            environ={},
            secret_getter=secrets.get,
        )

    captured = {}

    class Store:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def ensure_bucket(self):
            captured["ensured"] = True

    monkeypatch.setattr(distributed_documents, "S3ObjectStore", Store)
    settings["data_plane"]["object_store"]["allow_insecure"] = True
    object_store_from_settings(
        settings,
        environ={},
        secret_getter=secrets.get,
    )
    queue = job_queue_from_settings(
        {"data_plane": {}},
        environ={},
        secret_getter=secrets.get,
    )

    assert captured["allow_insecure"] is True
    assert captured["access_key"] == "access"
    assert captured["secret_key"] == "secret"
    assert captured["ensured"] is True
    assert "p%40ss%20word" in queue.dsn
    assert queue.dsn.endswith("sslmode=require")


class _WorkerQueue:
    def __init__(self, *, error=False):
        self.job_id, self.token = str(uuid.uuid4()), str(uuid.uuid4())
        self.error = error
        self.completed = []
        self.failed = []

    def claim(self, worker_id, *, lease_seconds):
        return {"id": self.job_id, "lease_token": self.token, "payload": {}}

    def heartbeat(self, *args, **kwargs):
        return True

    def cancel_requested(self, job_id):
        return False

    def complete(self, job_id, token, result):
        self.completed.append(result)

    def fail(self, job_id, token, error, *, retryable):
        self.failed.append(error)


def test_lease_worker_completes_or_retries_without_persisting_secret_text():
    success = _WorkerQueue()
    assert LeaseWorker(success, lambda context: {"ok": True}).run_once()
    assert success.completed == [{"ok": True}]

    failed = _WorkerQueue()

    def bad_handler(context):
        raise RuntimeError("token=customer-secret")

    assert LeaseWorker(failed, bad_handler).run_once()
    assert failed.failed == ["HandlerError:RuntimeError"]


def test_worker_encodes_postgres_credentials(monkeypatch):
    monkeypatch.setenv("TAXSENTRY_POSTGRES_PASSWORD", "p@ss:/ word")
    monkeypatch.setenv("TAXSENTRY_POSTGRES_SSLMODE", "verify-full")

    dsn = _postgres_dsn_from_env()

    assert "p%40ss%3A%2F%20word" in dsn
    assert dsn.endswith("sslmode=verify-full")
