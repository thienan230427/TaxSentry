from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Iterable
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .object_store import ObjectStore
from .queue import PostgresJobQueue

_SAFE_TABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}\Z")
SQLITE_SNAPSHOT_NAME = "snapshot.db"


@dataclass(slots=True)
class TableMigrationReport:
    imported: int = 0
    skipped: int = 0
    conflicts: int = 0
    object_refs: int = 0


@dataclass(slots=True)
class MigrationReport:
    imported: int = 0
    skipped: int = 0
    conflicts: int = 0
    object_refs: int = 0
    tables: dict[str, TableMigrationReport] = field(default_factory=dict)
    status: str = "completed"
    stage: str = ""
    error_type: str = ""


class MigrationFailure(RuntimeError):
    def __init__(self, report: MigrationReport) -> None:
        super().__init__("SQLite migration stopped before completion")
        self.report = report


@dataclass(frozen=True, slots=True)
class _ImportOutcome:
    status: str
    object_ref: bool = False


def export_sqlite_snapshot(database: Path, destination: Path) -> Path:
    """Export a transactionally consistent v2 SQLite snapshot as hashed JSONL."""
    database = database.resolve(strict=True)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "manifest.json"
    snapshot_destination = destination / SQLITE_SNAPSHOT_NAME
    with tempfile.TemporaryDirectory(prefix="taxsentry-sqlite-export-") as temporary:
        snapshot_path = Path(temporary) / SQLITE_SNAPSHOT_NAME
        with closing(_open_read_only(database)) as source, closing(
            sqlite3.connect(snapshot_path)
        ) as snapshot:
            source.backup(snapshot)
        temporary_snapshot = snapshot_destination.with_suffix(".db.tmp")
        try:
            shutil.copyfile(snapshot_path, temporary_snapshot)
            os.chmod(temporary_snapshot, 0o600)
            temporary_snapshot.replace(snapshot_destination)
        finally:
            temporary_snapshot.unlink(missing_ok=True)
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "source_name": database.name,
            "snapshot_file": snapshot_destination.name,
            "snapshot_sha256": _sha256_file(snapshot_destination),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "tables": {},
        }
        with closing(sqlite3.connect(snapshot_path)) as connection:
            connection.row_factory = sqlite3.Row
            tables = [
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            for table in tables:
                file_stem = (
                    table
                    if _SAFE_TABLE_NAME.fullmatch(table)
                    else f"table-{hashlib.sha256(table.encode()).hexdigest()[:16]}"
                )
                output_path = destination / f"{file_stem}.jsonl"
                temporary_path = output_path.with_suffix(".jsonl.tmp")
                count = 0
                with temporary_path.open("w", encoding="utf-8", newline="\n") as output:
                    query = f'SELECT * FROM "{table.replace(chr(34), chr(34) * 2)}"'
                    for row in connection.execute(query):
                        output.write(json.dumps(_json_safe(dict(row)), ensure_ascii=False) + "\n")
                        count += 1
                os.chmod(temporary_path, 0o600)
                temporary_path.replace(output_path)
                manifest["tables"][table] = {
                    "file": output_path.name,
                    "rows": count,
                    "sha256": _sha256_file(output_path),
                }
    temporary_manifest = manifest_path.with_suffix(".json.tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary_manifest, 0o600)
    temporary_manifest.replace(manifest_path)
    return manifest_path


def migrate_sqlite_jobs(
    database: Path,
    queue: PostgresJobQueue,
    *,
    company_id: str = "default",
) -> MigrationReport:
    """Idempotently import v2 jobs; other tables remain available in the export snapshot."""
    imported = skipped = 0
    with closing(_open_read_only(database.resolve(strict=True))) as connection:
        connection.row_factory = sqlite3.Row
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
        ).fetchone()
        if not exists:
            return MigrationReport(imported=0, skipped=0)
        for row in connection.execute("SELECT * FROM jobs ORDER BY created_at, id"):
            if queue.import_legacy_job(dict(row), company_id=company_id):
                imported += 1
            else:
                skipped += 1
    return MigrationReport(imported=imported, skipped=skipped)


def migrate_sqlite_database(
    database: Path,
    queue: PostgresJobQueue,
    *,
    company_id: str = "default",
    object_store: ObjectStore | None = None,
    legacy_source_root: Path | None = None,
    approved_legacy_roots: Iterable[Path] | None = None,
) -> MigrationReport:
    """Additively import the supported v2 tables without modifying the SQLite source."""
    database = database.resolve(strict=True)
    source_root = (
        legacy_source_root.expanduser().resolve(strict=True)
        if legacy_source_root is not None
        else database.parent
    )
    importer = _LegacyPostgresImporter(
        queue,
        object_store,
        source_root,
        approved_legacy_roots
        if approved_legacy_roots is not None
        else (source_root / "downloads", source_root / "outputs"),
    )
    report = MigrationReport(status="running", stage="import")
    with closing(_open_read_only(database.resolve(strict=True))) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        try:
            report = _migrate_connection(
                connection,
                importer,
                company_id.strip() or "default",
                report=report,
            )
        except Exception as exc:
            report.status = "partial" if report.imported or report.skipped else "failed"
            report.error_type = type(exc).__name__
            raise MigrationFailure(report) from exc
    report.status = "completed"
    report.stage = "completed"
    return report


def _migrate_connection(
    connection: sqlite3.Connection,
    importer,
    default_company_id: str,
    *,
    report: MigrationReport | None = None,
) -> MigrationReport:
    tables = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    report = report or MigrationReport()
    company_rows = {
        str(row.get("id") or row.get("company_id")): row
        for row in _rows(connection, tables, "companies")
        if row.get("id") or row.get("company_id")
    }
    session_company = {
        str(row["id"]): str(row.get("company_id") or default_company_id)
        for row in _rows(connection, tables, "sessions")
    }
    job_company = {
        str(row["id"]): str(row.get("company_id") or default_company_id)
        for row in _rows(connection, tables, "jobs")
    }
    company_ids = {default_company_id, *company_rows, *session_company.values(), *job_company.values()}
    for source_company_id in sorted(company_ids):
        _record(
            report,
            "companies",
            _safe_import(
                importer.company,
                source_company_id,
                company_rows.get(source_company_id, {}),
            ),
        )

    for row in _rows(connection, tables, "jobs", order_by="created_at, id"):
        _record(
            report,
            "jobs",
            _safe_import(
                importer.job,
                row,
                str(row.get("company_id") or default_company_id),
            ),
        )
    for row in _rows(connection, tables, "sessions", order_by="created_at, id"):
        _record(
            report,
            "sessions",
            _safe_import(
                importer.session,
                row,
                str(row.get("company_id") or default_company_id),
            ),
        )
    source_sessions = set(session_company)
    for row in _rows(connection, tables, "messages", order_by="created_at, id"):
        session_id = str(row.get("session_id") or "")
        if not session_id or session_id not in source_sessions:
            _record(report, "messages", _ImportOutcome("conflict"))
            continue
        source_company_id = session_company[session_id] or default_company_id
        row_company_id = str(row.get("company_id") or "").strip()
        if row_company_id and row_company_id != source_company_id:
            _record(report, "messages", _ImportOutcome("conflict"))
            continue
        _record(
            report,
            "messages",
            _safe_import(importer.message, row, source_company_id),
        )

    for table, method_name, order_by in (
        ("reports", "report", "created_at, id"),
        ("events", "event", "created_at, id"),
        ("deliveries", "delivery", "created_at, id"),
        ("attachments", "attachment", "id"),
    ):
        method = getattr(importer, method_name)
        for row in _rows(connection, tables, table, order_by=order_by):
            job_id = str(row.get("job_id") or "")
            global_event = table == "events" and not job_id
            if not global_event and (not job_id or job_id not in job_company):
                _record(report, table, _ImportOutcome("conflict"))
                continue
            source_company_id = job_company.get(job_id, default_company_id)
            _record(report, table, _safe_import(method, row, source_company_id))
    return report


class _LegacyPostgresImporter:
    def __init__(
        self,
        queue: PostgresJobQueue,
        object_store: ObjectStore | None,
        source_root: Path,
        approved_legacy_roots: Iterable[Path],
    ) -> None:
        self.queue = queue
        self.object_store = object_store
        self.source_root = source_root.resolve(strict=True)
        self.approved_legacy_roots = tuple(
            Path(os.path.abspath(Path(root).expanduser())) for root in approved_legacy_roots
        )

    def company(self, company_id: str, row: dict[str, Any]) -> _ImportOutcome:
        inserted = self._insert(
            """
            INSERT INTO taxsentry.companies
                (id, name, country_code, currency, profile, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """,
            (
                company_id,
                str(row.get("name") or ""),
                str(row.get("country_code") or "VN").upper()[:2],
                str(row.get("currency") or "VND").upper()[:3],
                _json_text(_parse_json(row.get("profile"), {})),
                _timestamp(row.get("created_at")),
                _timestamp(row.get("updated_at") or row.get("created_at")),
            ),
        )
        return _ImportOutcome("imported" if inserted else "skipped")

    def job(self, row: dict[str, Any], company_id: str) -> _ImportOutcome:
        inserted = self.queue.import_legacy_job(row, company_id=company_id)
        return _ImportOutcome("imported" if inserted else "skipped")

    def session(self, row: dict[str, Any], company_id: str) -> _ImportOutcome:
        session_id = _stable_uuid(row.get("id"), "session")
        system_prompt = str(row.get("system_prompt") or "")
        prompt_hash = str(row.get("system_prompt_hash") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", prompt_hash):
            prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO taxsentry.sessions
                    (id, company_id, platform, provider, model, system_prompt_hash,
                     system_prompt, provider_thread_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (
                    session_id,
                    company_id,
                    str(row.get("platform") or "terminal"),
                    str(row.get("provider") or "unknown"),
                    str(row.get("model") or ""),
                    prompt_hash.lower(),
                    system_prompt,
                    str(row.get("provider_thread_id") or ""),
                    _timestamp(row.get("created_at")),
                    _timestamp(row.get("updated_at") or row.get("created_at")),
                ),
            )
            inserted = cursor.fetchone() is not None
            summary = str(row.get("summary") or "").strip()
            if summary:
                cursor.execute(
                    """
                    INSERT INTO taxsentry.session_summaries
                        (session_id, company_id, summary, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    (
                        session_id,
                        company_id,
                        summary,
                        _timestamp(row.get("updated_at") or row.get("created_at")),
                    ),
                )
        return _ImportOutcome("imported" if inserted else "skipped")

    def message(self, row: dict[str, Any], company_id: str) -> _ImportOutcome:
        inserted = self._insert(
            """
            INSERT INTO taxsentry.messages
                (id, session_id, company_id, role, content, source, trusted,
                 pinned, expires_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """,
            (
                _stable_uuid(row.get("id"), "message"),
                _stable_uuid(row.get("session_id"), "session"),
                company_id,
                str(row.get("role") or "user"),
                str(row.get("content") or ""),
                str(row.get("source") or "terminal"),
                _bool(row.get("trusted"), True),
                _bool(row.get("pinned"), False),
                _optional_timestamp(row.get("expires_at")),
                _timestamp(row.get("created_at")),
            ),
        )
        return _ImportOutcome("imported" if inserted else "skipped")

    def report(self, row: dict[str, Any], company_id: str) -> _ImportOutcome:
        payload = _parse_json(row.get("payload"), {"raw": str(row.get("payload") or "")})
        spec = {
            "legacy_job_id": str(row.get("job_id") or ""),
            "confidence": float(row.get("confidence") or 0),
            "payload": payload,
        }
        content = _json_text(spec).encode()
        pdf_path = self._source_path(row.get("pdf_path"))
        if self.object_store is not None and pdf_path:
            digest = _sha256_file(pdf_path)
            suffix = pdf_path.suffix.casefold() or ".pdf"
            object_key = (
                f"legacy/reports/{_company_namespace(company_id)}/{digest}{suffix}"
            )
        else:
            digest = hashlib.sha256(content).hexdigest()
            object_key = (
                f"legacy-metadata/reports/{_company_namespace(company_id)}/{digest}.json"
            )
        identity_digest = hashlib.sha256(content + digest.encode()).hexdigest()
        report_id = _tenant_uuid(row.get("id"), "report", company_id, identity_digest)
        if self._exists("artifacts", "id=%s", (report_id,)):
            return _ImportOutcome("skipped")
        object_ref = False
        if self.object_store is not None and pdf_path:
            stored = self.object_store.put_file(object_key, pdf_path, sha256=digest)
            object_ref = True
        elif self.object_store is not None:
            stored = self.object_store.put_bytes(object_key, content)
            object_ref = True
        else:
            stored = None
        if stored is not None:
            digest = stored.sha256
        inserted = self._insert(
            """
            INSERT INTO taxsentry.artifacts
                (id, company_id, kind, object_key, sha256, spec, status, created_at)
            VALUES (%s, %s, 'legacy-report', %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
            """,
            (
                report_id,
                company_id,
                object_key,
                digest,
                _json_text(spec),
                "imported" if object_ref else "metadata_only",
                _timestamp(row.get("created_at")),
            ),
        )
        return _ImportOutcome("imported" if inserted else "skipped", object_ref and inserted)

    def event(self, row: dict[str, Any], company_id: str) -> _ImportOutcome:
        event_id = _stable_uuid(row.get("id"), "event")
        parsed_payload = _parse_json(row.get("payload"), {"raw": row.get("payload")})
        payload = _json_text(parsed_payload)
        job_id = row.get("job_id")
        if job_id:
            inserted = self._insert(
                """
                INSERT INTO taxsentry.job_events (id, job_id, kind, payload, created_at)
                VALUES (%s, %s, %s, %s::jsonb, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (
                    event_id,
                    _legacy_job_uuid(job_id),
                    str(row.get("kind") or "legacy"),
                    payload,
                    _timestamp(row.get("created_at")),
                ),
            )
        else:
            inserted = self._insert(
                """
                INSERT INTO taxsentry.audit_events
                    (id, company_id, actor, kind, target_type, target_id, metadata, created_at)
                VALUES (%s, %s, 'sqlite-migration', %s, 'legacy-event', %s, %s::jsonb, %s)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """,
                (
                    event_id,
                    company_id,
                    str(row.get("kind") or "legacy"),
                    str(row.get("id") or event_id),
                    _json_text(
                        {
                            "legacy_scope": "global",
                            "payload": parsed_payload,
                        }
                    ),
                    _timestamp(row.get("created_at")),
                ),
            )
        return _ImportOutcome("imported" if inserted else "skipped")

    def delivery(self, row: dict[str, Any], company_id: str) -> _ImportOutcome:
        del company_id
        inserted = self._insert(
            """
            INSERT INTO taxsentry.deliveries
                (id, job_id, channel, external_id, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                _stable_uuid(row.get("id"), "delivery"),
                _legacy_job_uuid(row.get("job_id")),
                str(row.get("channel") or "unknown"),
                str(row.get("external_id") or ""),
                str(row.get("status") or "unknown"),
                _timestamp(row.get("created_at")),
            ),
        )
        return _ImportOutcome("imported" if inserted else "skipped")

    def attachment(self, row: dict[str, Any], company_id: str) -> _ImportOutcome:
        if self.object_store is None:
            return _ImportOutcome("skipped")
        source = self._source_path(row.get("path"))
        if source is None:
            return _ImportOutcome("conflict")
        expected = str(row.get("sha256") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            return _ImportOutcome("conflict")
        if _sha256_file(source) != expected:
            return _ImportOutcome("conflict")
        if self._exists(
            "documents",
            "company_id=%s AND sha256=%s",
            (company_id, expected),
        ):
            return _ImportOutcome("skipped")
        suffix = Path(str(row.get("name") or source.name)).suffix.casefold()
        object_key = (
            f"legacy/attachments/{_company_namespace(company_id)}/{expected}{suffix}"
        )
        stored = self.object_store.put_file(object_key, source, sha256=expected)
        document_id = hashlib.sha256(f"{company_id}:{expected}".encode()).hexdigest()[:32]
        inserted = self._insert(
            """
            INSERT INTO taxsentry.documents
                (id, company_id, sha256, name, mime_type, size_bytes,
                 raw_object_key, manifest, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                document_id,
                company_id,
                stored.sha256,
                str(row.get("name") or source.name),
                str(row.get("mime_type") or "application/octet-stream"),
                stored.size,
                stored.key,
                _json_text(
                    {
                        "source": "taxsentry-v2-sqlite",
                        "legacy_job_id": str(row.get("job_id") or ""),
                        "legacy_name": source.name,
                    }
                ),
                _timestamp(row.get("created_at")),
            ),
        )
        return _ImportOutcome("imported" if inserted else "skipped", inserted)

    def _insert(self, statement: str, params: tuple[Any, ...]) -> bool:
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(statement, params)
            return cursor.fetchone() is not None

    def _exists(self, table: str, where: str, params: tuple[Any, ...]) -> bool:
        if table not in {"artifacts", "documents"}:
            raise ValueError("Unsupported migration conflict check")
        with self.queue._connect() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT 1 FROM taxsentry.{table} WHERE {where}", params)
            return cursor.fetchone() is not None

    def _source_path(self, value: Any) -> Path | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        supplied = Path(raw).expanduser()
        candidate = supplied if supplied.is_absolute() else self.source_root / supplied
        candidate = Path(os.path.abspath(candidate))
        for root in self.approved_legacy_roots:
            root = Path(os.path.abspath(root))
            if root.is_symlink():
                raise ValueError("Approved legacy roots may not be symlinks")
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                continue
            current = root
            for part in relative.parts:
                current /= part
                if current.is_symlink():
                    raise ValueError("Legacy source path may not contain symlinks")
            resolved_root = root.resolve(strict=True)
            resolved = candidate.resolve(strict=True)
            if resolved.is_file() and (resolved == resolved_root or resolved_root in resolved.parents):
                return resolved
        raise ValueError("Legacy source path is outside approved roots")


def _rows(
    connection: sqlite3.Connection,
    tables: set[str],
    table: str,
    *,
    order_by: str = "id",
):
    if table not in tables:
        return
    query = f'SELECT * FROM "{table}" ORDER BY {order_by}'
    for row in connection.execute(query):
        yield dict(row)


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    quoted = table.replace('"', '""')
    return {str(row["name"]) for row in connection.execute(f'PRAGMA table_info("{quoted}")')}


def _safe_import(method, *args) -> _ImportOutcome:
    try:
        return method(*args)
    except (FileNotFoundError, ValueError):
        return _ImportOutcome("conflict")


def _record(report: MigrationReport, table: str, outcome: _ImportOutcome) -> None:
    table_report = report.tables.setdefault(table, TableMigrationReport())
    if outcome.status == "imported":
        report.imported += 1
        table_report.imported += 1
    elif outcome.status == "skipped":
        report.skipped += 1
        table_report.skipped += 1
    else:
        report.conflicts += 1
        table_report.conflicts += 1
    if outcome.object_ref:
        report.object_refs += 1
        table_report.object_refs += 1


def _stable_uuid(value: Any, kind: str) -> str:
    source = str(value or "")
    try:
        return str(uuid.UUID(source))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"taxsentry-v2:{kind}:{source}"))


def _tenant_uuid(value: Any, kind: str, company_id: str, digest: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"taxsentry-v2:{company_id}:{kind}:{value or ''}:{digest}",
        )
    )


def _company_namespace(company_id: str) -> str:
    return hashlib.sha256(company_id.encode()).hexdigest()[:16]


def _legacy_job_uuid(value: Any) -> str:
    source = str(value or "")
    try:
        return str(uuid.UUID(source))
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"taxsentry-v2:{source}"))


def _parse_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _timestamp(value: Any) -> str:
    return str(value or "1970-01-01T00:00:00+00:00")


def _optional_timestamp(value: Any) -> str | None:
    return str(value) if value else None


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


def write_migration_report(report: MigrationReport, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(destination)


def _open_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
