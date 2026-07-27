from __future__ import annotations

import hashlib
import os
import time
import uuid

import pytest
from openpyxl import Workbook

from taxsentry.data_plane import DistributedDocumentService, PostgresAgentStore
from taxsentry.data_plane.migration import (
    export_sqlite_snapshot,
    migrate_sqlite_database,
)
from taxsentry.data_plane.object_store import S3ObjectStore
from taxsentry.data_plane.queue import PostgresJobQueue
from taxsentry.documents import DocumentService
from taxsentry.store import JobStore


@pytest.mark.skipif(
    not os.environ.get("TAXSENTRY_TEST_POSTGRES_DSN"),
    reason="set TAXSENTRY_TEST_POSTGRES_DSN for PostgreSQL integration",
)
def test_postgres_queue_lease_retry_checkpoint_and_resume():
    queue = PostgresJobQueue(os.environ["TAXSENTRY_TEST_POSTGRES_DSN"])
    queue.ensure_schema()
    company_id = f"integration-{uuid.uuid4()}"
    job = queue.enqueue(
        company_id=company_id,
        payload={"document": "fixture.xlsx"},
        idempotency_key="one",
        priority=2_147_483_647,
        max_attempts=2,
    )
    claimed = queue.claim("integration-worker", lease_seconds=30)
    assert claimed and claimed["id"] == job["id"]
    queue.checkpoint(
        str(job["id"]),
        str(claimed["lease_token"]),
        "extract",
        {"sheet": 1},
        processed=1,
        total=2,
    )
    retried = queue.fail(
        str(job["id"]),
        str(claimed["lease_token"]),
        "fixture failure",
        retryable=True,
    )
    assert retried["state"] == "queued"
    claimed = queue.claim("integration-worker", lease_seconds=30)
    completed = queue.complete(str(job["id"]), str(claimed["lease_token"]), {"ok": True})
    assert completed["state"] == "completed"

    cancelled = queue.enqueue(company_id=company_id, payload={}, idempotency_key="cancel")
    assert queue.request_cancel(str(cancelled["id"]))
    resumed = queue.resume(str(cancelled["id"]))
    assert resumed and resumed["state"] == "queued"
    resumed_claim = queue.claim("integration-worker", lease_seconds=30)
    assert resumed_claim and resumed_claim["id"] == cancelled["id"]
    queue.complete(
        str(cancelled["id"]),
        str(resumed_claim["lease_token"]),
        {"resumed": True},
    )


@pytest.mark.skipif(
    not os.environ.get("TAXSENTRY_TEST_POSTGRES_DSN"),
    reason="set TAXSENTRY_TEST_POSTGRES_DSN for PostgreSQL agent-store integration",
)
def test_postgres_agent_memory_and_sessions_are_company_scoped_and_forgettable():
    queue = PostgresJobQueue(os.environ["TAXSENTRY_TEST_POSTGRES_DSN"])
    queue.ensure_schema()
    alpha_id = f"agent-alpha-{uuid.uuid4()}"
    beta_id = f"agent-beta-{uuid.uuid4()}"
    alpha = PostgresAgentStore(queue, company_id=alpha_id)
    beta = PostgresAgentStore(queue, company_id=beta_id)
    alpha.upsert_company(name="Alpha")
    beta.upsert_company(name="Beta")
    session_id = alpha.create_session(
        "lmstudio",
        platform="shared",
        company_id=alpha_id,
        system_prompt="snapshot",
        system_prompt_hash=hashlib.sha256(b"snapshot").hexdigest(),
    )
    message_id = alpha.add_message(
        session_id,
        "user",
        "Quyết định đã xác nhận",
        company_id=alpha_id,
        source="terminal",
        trusted=True,
    )
    alpha.update_session_summary(session_id, "Quyết định đã xác nhận")
    private = alpha.save_memory(
        "Alpha uses VND",
        company_id=alpha_id,
        kind="preference",
        provenance='{"source":"terminal"}',
        sensitivity="internal",
        trusted=True,
    )
    beta.save_memory(
        "Beta uses USD",
        company_id=beta_id,
        kind="preference",
        provenance='{"source":"terminal"}',
        sensitivity="internal",
        trusted=True,
    )
    alpha.save_memory(
        "Global reporting convention",
        company_id="__global__",
        kind="convention",
        provenance='{"source":"system"}',
        sensitivity="internal",
        trusted=True,
    )

    resumed = PostgresAgentStore(queue, company_id=alpha_id)
    assert resumed.session(session_id)["summary"] == "Quyết định đã xác nhận"
    assert resumed.session_messages(session_id)[0]["id"] == message_id
    assert resumed.search_sessions("Quyết định", company_id=alpha_id)
    contents = {
        item["content"]
        for item in resumed.memory_items(company_id=alpha_id, include_global=True)
    }
    assert "Alpha uses VND" in contents
    assert "Global reporting convention" in contents
    assert "Beta uses USD" not in contents
    assert resumed.forget_memory(private["id"], company_id=alpha_id)
    tombstone = resumed.memory_tombstone(private["id"])
    assert tombstone and "content" not in tombstone
    assert not resumed.memory_items(
        company_id=alpha_id,
        query="Alpha uses VND",
        include_global=False,
    )



@pytest.mark.skipif(
    not (
        os.environ.get("TAXSENTRY_TEST_POSTGRES_DSN")
        and os.environ.get("TAXSENTRY_TEST_LEASE_RECOVERY")
    ),
    reason="set lease-recovery flag and stop competing workers",
)
def test_postgres_expired_lease_resumes_from_checkpoint():
    queue = PostgresJobQueue(os.environ["TAXSENTRY_TEST_POSTGRES_DSN"])
    queue.ensure_schema()
    with queue._connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM taxsentry.jobs WHERE company_id LIKE %s",
            ("lease-recovery-%",),
        )
    company_id = f"lease-recovery-{uuid.uuid4()}"
    orphaned = queue.enqueue(
        company_id=company_id,
        payload={"document": "restart.xlsx"},
        idempotency_key="restart",
        priority=2_147_483_647,
    )
    first_lease = queue.claim("worker-before-restart", lease_seconds=5)
    assert first_lease and first_lease["id"] == orphaned["id"]
    queue.checkpoint(
        str(orphaned["id"]),
        str(first_lease["lease_token"]),
        "inventory",
        {"sheet": 12},
        processed=12,
        total=20,
    )
    time.sleep(6)

    replacement = queue.claim("worker-after-restart", lease_seconds=30)

    assert replacement and replacement["id"] == orphaned["id"]
    assert queue.steps(str(orphaned["id"]))[0]["checkpoint"]["sheet"] == 12
    queue.complete(
        str(orphaned["id"]),
        str(replacement["lease_token"]),
        {"resumed": True},
    )


@pytest.mark.skipif(
    not os.environ.get("TAXSENTRY_TEST_S3_ENDPOINT"),
    reason="set TAXSENTRY_TEST_S3_ENDPOINT and S3 credentials for MinIO integration",
)
def test_minio_round_trip():
    store = S3ObjectStore(
        endpoint_url=os.environ["TAXSENTRY_TEST_S3_ENDPOINT"],
        bucket=os.environ.get("TAXSENTRY_TEST_S3_BUCKET", "taxsentry-tests"),
        access_key=os.environ["TAXSENTRY_TEST_S3_ACCESS_KEY"],
        secret_key=os.environ["TAXSENTRY_TEST_S3_SECRET_KEY"],
        allow_insecure=os.environ["TAXSENTRY_TEST_S3_ENDPOINT"].startswith("http://"),
    )
    store.ensure_bucket()
    key = f"integration/{uuid.uuid4()}.bin"
    try:
        store.put_bytes(key, b"taxsentry")
        assert store.get_bytes(key) == b"taxsentry"
    finally:
        store.delete(key)


@pytest.mark.skipif(
    not (
        os.environ.get("TAXSENTRY_TEST_POSTGRES_DSN")
        and os.environ.get("TAXSENTRY_TEST_S3_ENDPOINT")
    ),
    reason="set PostgreSQL and S3 integration variables for worker round-trip",
)
def test_distributed_document_worker_round_trip(tmp_path):
    queue = PostgresJobQueue(os.environ["TAXSENTRY_TEST_POSTGRES_DSN"])
    queue.ensure_schema()
    store = S3ObjectStore(
        endpoint_url=os.environ["TAXSENTRY_TEST_S3_ENDPOINT"],
        bucket=os.environ.get("TAXSENTRY_TEST_S3_WORKER_BUCKET", "taxsentry"),
        access_key=os.environ["TAXSENTRY_TEST_S3_ACCESS_KEY"],
        secret_key=os.environ["TAXSENTRY_TEST_S3_SECRET_KEY"],
        allow_insecure=True,
    )
    store.ensure_bucket()
    workbook_path = tmp_path / "worker-case.xlsx"
    workbook = Workbook()
    workbook.active.title = "Kỳ Này"
    workbook.active.append(["Chỉ tiêu", "Số tiền"])
    workbook.active.append(["Doanh thu thuần", 580])
    hidden = workbook.create_sheet("Tổng hợp thuế")
    hidden.sheet_state = "hidden"
    hidden.append(["Thuế GTGT", 58])
    workbook.save(workbook_path)

    service = DistributedDocumentService(
        queue=queue,
        object_store=store,
        local_service=DocumentService(tmp_path / "local-index"),
        poll_seconds=0.1,
        timeout_seconds=120,
    )
    company_id = f"integration-{uuid.uuid4()}"
    manifest = service.ingest_sync(
        path=workbook_path,
        company_id=company_id,
        case_id=f"case-{uuid.uuid4()}",
    )

    assert manifest.company_id == company_id
    assert manifest.coverage.complete
    assert manifest.metadata["sheets"][1]["state"] == "hidden"
    assert service.query_sync(
        document_id=manifest.id,
        company_id=company_id,
        query="Doanh thu thuần",
    )[0].locator.startswith("sheet=Kỳ Này!")


@pytest.mark.skipif(
    not (
        os.environ.get("TAXSENTRY_TEST_POSTGRES_DSN")
        and os.environ.get("TAXSENTRY_TEST_S3_ENDPOINT")
    ),
    reason="set PostgreSQL and S3 integration variables for migration rehearsal",
)
def test_live_sqlite_migration_is_additive_idempotent_and_preserves_source(tmp_path):
    queue = PostgresJobQueue(os.environ["TAXSENTRY_TEST_POSTGRES_DSN"])
    queue.ensure_schema()
    objects = S3ObjectStore(
        endpoint_url=os.environ["TAXSENTRY_TEST_S3_ENDPOINT"],
        bucket=os.environ.get("TAXSENTRY_TEST_S3_WORKER_BUCKET", "taxsentry"),
        access_key=os.environ["TAXSENTRY_TEST_S3_ACCESS_KEY"],
        secret_key=os.environ["TAXSENTRY_TEST_S3_SECRET_KEY"],
        allow_insecure=True,
    )
    objects.ensure_bucket()
    company_id = f"migration-{uuid.uuid4()}"
    database = tmp_path / "legacy.db"
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    attachment = downloads / "evidence.txt"
    attachment.write_text("migration evidence", encoding="utf-8")
    legacy = JobStore(database)
    job = legacy.create_job(f"message-{uuid.uuid4()}", "boss@example.test", "Case")
    assert job
    legacy.attachment(
        job["id"],
        name=attachment.name,
        path=str(attachment),
        sha256=hashlib.sha256(attachment.read_bytes()).hexdigest(),
        mime_type="text/plain",
    )
    legacy.event(job["id"], "migration_rehearsal", {"ok": True})
    legacy.report(job["id"], {"summary": "Verified"}, 1.0)
    legacy.delivery(job["id"], "test", "sent", "delivery-1")
    session_id = legacy.create_session(
        "lmstudio",
        company_id=company_id,
        system_prompt="snapshot",
        system_prompt_hash=hashlib.sha256(b"snapshot").hexdigest(),
    )
    legacy.add_message(
        session_id,
        "user",
        "Remember this verified decision",
        company_id=company_id,
        source="terminal",
        trusted=True,
    )
    legacy.close()
    source_digest = hashlib.sha256(database.read_bytes()).hexdigest()

    manifest = export_sqlite_snapshot(database, tmp_path / "backup")
    snapshot = manifest.parent / "snapshot.db"
    first = migrate_sqlite_database(
        snapshot,
        queue,
        company_id=company_id,
        object_store=objects,
        legacy_source_root=database.parent,
    )
    second = migrate_sqlite_database(
        snapshot,
        queue,
        company_id=company_id,
        object_store=objects,
        legacy_source_root=database.parent,
    )

    assert manifest.is_file()
    assert (manifest.parent / "snapshot.db").is_file()
    assert first.imported >= 7 and first.conflicts == 0
    assert second.imported == 0 and second.skipped >= first.imported
    migrated_job = queue.get(job["id"])
    assert migrated_job and migrated_job["state"] == "failed"
    assert migrated_job["payload"]["legacy_replay_blocked"] is True
    assert hashlib.sha256(database.read_bytes()).hexdigest() == source_digest
