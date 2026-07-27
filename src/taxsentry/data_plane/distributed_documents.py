from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote, urlencode

from .object_store import LocalObjectStore, ObjectStore, S3ObjectStore
from .queue import JobQueue, PostgresJobQueue


class DistributedDocumentError(RuntimeError):
    """Base error for coordinator-side distributed document jobs."""


class DocumentJobFailed(DistributedDocumentError):
    pass


class DocumentJobCancelled(DistributedDocumentError):
    pass


class DocumentJobTimeout(TimeoutError, DistributedDocumentError):
    pass


class DistributedDocumentService:
    """Submit bounded document jobs and restore their results into a local index."""

    def __init__(
        self,
        *,
        queue: PostgresJobQueue,
        object_store: ObjectStore,
        local_service=None,
        poll_seconds: float = 1.0,
        timeout_seconds: float = 7_200,
        max_document_bytes: int = 500 * 1024 * 1024,
        excel_rows_per_unit: int = 250,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 < poll_seconds <= 60:
            raise ValueError("poll_seconds must be between 0 and 60")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_document_bytes <= 0:
            raise ValueError("max_document_bytes must be positive")
        if excel_rows_per_unit < 1:
            raise ValueError("excel_rows_per_unit must be positive")
        from taxsentry.documents import DOCUMENT_EXTRACTION_SCHEMA_VERSION

        if local_service is None:
            from taxsentry.documents import DocumentService

            local_service = DocumentService(
                excel_rows_per_unit=excel_rows_per_unit,
            )
        self.queue = queue
        self.object_store = object_store
        self.local_service = local_service
        self.poll_seconds = float(poll_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self.max_document_bytes = int(max_document_bytes)
        self.extraction = {
            "schema_version": DOCUMENT_EXTRACTION_SCHEMA_VERSION,
            "excel_rows_per_unit": int(excel_rows_per_unit),
        }
        self._active_jobs: dict[tuple[str, str], set[str]] = {}
        self._active_lock = Lock()
        self._sleep = sleep
        self._monotonic = monotonic

    @classmethod
    def from_settings(
        cls,
        settings: Mapping[str, Any] | None = None,
        *,
        dsn: str | None = None,
        queue: PostgresJobQueue | None = None,
        object_store: ObjectStore | None = None,
        local_service=None,
        environ: Mapping[str, str] | None = None,
        secret_getter: Callable[[str], str] | None = None,
        ensure_schema: bool = True,
    ) -> DistributedDocumentService:
        if settings is None:
            from taxsentry.config import load_config

            settings = load_config()
        data_plane = _mapping(settings.get("data_plane"))
        worker = _mapping(settings.get("worker"))
        documents = _mapping(settings.get("documents"))
        if queue is None:
            queue = job_queue_from_settings(
                settings,
                dsn=dsn,
                environ=environ,
                secret_getter=secret_getter,
            )
            if ensure_schema:
                queue.ensure_schema()
        injected_object_store = object_store is not None
        object_store = object_store or object_store_from_settings(
            settings,
            environ=environ,
            secret_getter=secret_getter,
        )
        if (
            isinstance(object_store, LocalObjectStore)
            and not injected_object_store
            and not _local_store_is_shared(data_plane, environ)
        ):
            raise ValueError(
                "Distributed mode requires S3/MinIO or an explicitly shared local "
                "object store (data_plane.object_store.shared=true)"
            )
        return cls(
            queue=queue,
            object_store=object_store,
            local_service=local_service,
            poll_seconds=float(data_plane.get("poll_seconds") or 1),
            timeout_seconds=float(
                data_plane.get("document_timeout_seconds")
                or worker.get("extraction_timeout_seconds")
                or 7_200
            ),
            max_document_bytes=int(
                float(documents.get("max_case_mb") or 500) * 1024 * 1024
            ),
            excel_rows_per_unit=int(
                documents.get("excel_rows_per_unit") or 250
            ),
        )

    async def ingest(
        self,
        *,
        path: Path,
        company_id: str,
        case_id: str = "",
        languages: list[str] | None = None,
        timeout_seconds: float | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        budget: Mapping[str, Any] | None = None,
    ):
        return await asyncio.to_thread(
            self.ingest_sync,
            path=path,
            company_id=company_id,
            case_id=case_id,
            languages=languages,
            timeout_seconds=timeout_seconds,
            priority=priority,
            max_attempts=max_attempts,
            budget=budget,
        )

    def ingest_sync(
        self,
        *,
        path: Path,
        company_id: str,
        case_id: str = "",
        languages: list[str] | None = None,
        timeout_seconds: float | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        budget: Mapping[str, Any] | None = None,
    ):
        from taxsentry.documents import validate_document

        resolved = path.expanduser().resolve(strict=True)
        suffix = validate_document(resolved, max_bytes=self.max_document_bytes)
        if not isinstance(company_id, str):
            raise ValueError("company_id is required")
        company = company_id.strip()
        if not company:
            raise ValueError("company_id is required")
        if languages is not None and (
            not isinstance(languages, list)
            or not languages
            or any(not isinstance(language, str) for language in languages)
        ):
            raise ValueError("languages must contain non-empty strings")
        selected_languages = [
            language.strip() for language in (languages or ["vie", "eng"])
        ]
        if any(not language for language in selected_languages):
            raise ValueError("languages must contain non-empty strings")
        digest = _sha256_file(resolved)
        if not isinstance(case_id, str):
            raise ValueError("case_id must be a string")
        resolved_case = case_id.strip() or hashlib.sha256(
            f"{company}:{digest}".encode()
        ).hexdigest()[:32]
        company_namespace = hashlib.sha256(company.encode()).hexdigest()[:16]
        raw_key = f"documents/raw/{company_namespace}/{digest}{suffix}"
        raw_object = self.object_store.put_file(raw_key, resolved, sha256=digest)
        if raw_object.sha256 != digest:
            raise DistributedDocumentError("Raw object SHA-256 verification failed")
        request_digest = hashlib.sha256(
            json.dumps(
                {
                    "company_id": company,
                    "case_id": resolved_case,
                    "sha256": digest,
                    "languages": selected_languages,
                    "extraction": self.extraction,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        idempotency_key = f"document:{request_digest}"
        result_prefix = f"documents/results/{request_digest}"
        job = self.queue.enqueue(
            company_id=company,
            case_id=resolved_case,
            idempotency_key=idempotency_key,
            priority=priority,
            max_attempts=max_attempts,
            budget=budget or {},
            payload={
                "object_key": raw_key,
                "company_id": company,
                "case_id": resolved_case,
                "languages": selected_languages,
                "name": resolved.name,
                "sha256": digest,
                "request_digest": request_digest,
                "result_prefix": result_prefix,
                "extraction": self.extraction,
            },
        )
        job_id = str(job["id"])
        if str(job.get("state") or "") in {"failed", "cancelled"}:
            job = self.queue.resume(job_id) or self.queue.get(job_id)
            if job is None:
                raise DistributedDocumentError(
                    f"Document job disappeared while resuming: {job_id}"
                )
        self._track_job(company, resolved_case, job_id)
        try:
            return self._wait(
                job,
                company_id=company,
                case_id=resolved_case,
                sha256=digest,
                result_prefix=result_prefix,
                timeout_seconds=timeout_seconds,
            )
        finally:
            self._untrack_job(company, resolved_case, job_id)

    def cancel(self, job_id: str) -> bool:
        return self.queue.request_cancel(job_id)

    def cancel_case(self, case_id: str, *, company_id: str) -> bool:
        key = (company_id.strip(), case_id.strip())
        if not all(key):
            raise ValueError("company_id and case_id are required")
        with self._active_lock:
            job_ids = tuple(sorted(self._active_jobs.get(key, ())))
        cancelled = False
        for job_id in job_ids:
            cancelled = self.queue.request_cancel(job_id) or cancelled
        return cancelled

    def get_manifest(self, document_id: str, *, company_id: str):
        return self._ensure_local(document_id, company_id=company_id)

    def analysis_content(self, document_id: str, *, company_id: str):
        self._ensure_local(document_id, company_id=company_id)
        return self.local_service.analysis_content(
            document_id,
            company_id=company_id,
        )

    def iter_units(self, document_id: str, *, company_id: str) -> Iterator[Any]:
        self._ensure_local(document_id, company_id=company_id)
        return self.local_service.iter_units(
            document_id,
            company_id=company_id,
        )

    def prompt_partitions(
        self,
        document_ids: Iterable[str],
        *,
        company_id: str,
        max_chars: int = 60_000,
    ) -> Iterator[str]:
        ids = tuple(document_ids)
        for document_id in ids:
            self._ensure_local(document_id, company_id=company_id)
        return self.local_service.prompt_partitions(
            ids,
            company_id=company_id,
            max_chars=max_chars,
        )

    def query_sync(
        self,
        *,
        document_id: str,
        company_id: str,
        query: str,
        limit: int = 20,
    ):
        self._ensure_local(document_id, company_id=company_id)
        return self.local_service.query_sync(
            document_id=document_id,
            company_id=company_id,
            query=query,
            limit=limit,
        )

    async def query(
        self,
        *,
        document_id: str,
        company_id: str,
        query: str,
        limit: int = 20,
    ):
        self._ensure_local(document_id, company_id=company_id)
        return await self.local_service.query(
            document_id=document_id,
            company_id=company_id,
            query=query,
            limit=limit,
        )

    async def coverage(self, document_id: str, *, company_id: str):
        self._ensure_local(document_id, company_id=company_id)
        return await self.local_service.coverage(
            document_id,
            company_id=company_id,
        )

    def _wait(
        self,
        job: Mapping[str, Any],
        *,
        company_id: str,
        case_id: str,
        sha256: str,
        result_prefix: str,
        timeout_seconds: float | None,
    ):
        timeout = self.timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        deadline = self._monotonic() + timeout
        current = dict(job)
        job_id = str(current["id"])
        while True:
            state = str(current.get("state") or "")
            if state == "completed":
                return self._materialize(
                    current,
                    company_id=company_id,
                    case_id=case_id,
                    sha256=sha256,
                    result_prefix=result_prefix,
                )
            if state == "failed":
                raise DocumentJobFailed(f"Distributed document job failed: {job_id}")
            if state == "cancelled":
                raise DocumentJobCancelled(
                    f"Distributed document job was cancelled: {job_id}"
                )
            if state not in {"queued", "running"}:
                raise DistributedDocumentError(
                    f"Distributed document job has an invalid state: {job_id}"
                )
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                self.queue.request_cancel(job_id)
                raise DocumentJobTimeout(
                    f"Timed out waiting for distributed document job: {job_id}"
                )
            self._sleep(min(self.poll_seconds, remaining))
            refreshed = self.queue.get(job_id)
            if refreshed is None:
                raise DistributedDocumentError(
                    f"Distributed document job was not found: {job_id}"
                )
            current = refreshed

    def _track_job(self, company_id: str, case_id: str, job_id: str) -> None:
        with self._active_lock:
            self._active_jobs.setdefault((company_id, case_id), set()).add(job_id)

    def _untrack_job(self, company_id: str, case_id: str, job_id: str) -> None:
        with self._active_lock:
            key = (company_id, case_id)
            jobs = self._active_jobs.get(key)
            if not jobs:
                return
            jobs.discard(job_id)
            if not jobs:
                self._active_jobs.pop(key, None)

    def _materialize(
        self,
        job: Mapping[str, Any],
        *,
        company_id: str,
        case_id: str,
        sha256: str,
        result_prefix: str,
    ):
        result = job.get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError as exc:
                raise DistributedDocumentError(
                    "Distributed document result is not valid JSON"
                ) from exc
        if not isinstance(result, Mapping):
            raise DistributedDocumentError("Distributed document result is missing")
        return self._restore_result(
            result,
            company_id=company_id,
            case_id=case_id,
            sha256=sha256,
            result_prefix=result_prefix,
        )

    def _restore_result(
        self,
        result: Mapping[str, Any],
        *,
        company_id: str,
        case_id: str,
        sha256: str,
        result_prefix: str,
    ):
        if (
            str(result.get("company_id") or "") != company_id
            or str(result.get("case_id") or "") != case_id
            or _required_result_sha256(result, "raw_sha256") != sha256
        ):
            raise DistributedDocumentError(
                "Distributed document result scope does not match its request"
            )
        raw_key = _required_result_key(result, "raw_key")
        manifest_key = _scoped_result_key(
            result,
            "manifest_key",
            result_prefix,
            "manifest.json",
        )
        units_key = _scoped_result_key(
            result,
            "units_key",
            result_prefix,
            "units.jsonl",
        )
        manifest_sha256 = _required_result_sha256(result, "manifest_sha256")
        units_sha256 = _required_result_sha256(result, "units_sha256")
        analysis_key = str(result.get("analysis_key") or "")
        analysis_sha256 = str(result.get("analysis_sha256") or "")
        if bool(analysis_key) != bool(analysis_sha256):
            raise DistributedDocumentError(
                "Distributed document analysis key/checksum is incomplete"
            )
        if analysis_key:
            analysis_key = _scoped_result_key(
                result,
                "analysis_key",
                result_prefix,
                "analysis.json",
            )
            analysis_sha256 = _required_result_sha256(result, "analysis_sha256")
        local_root = getattr(self.local_service, "root", None)
        temporary_parent = Path(local_root).parent if local_root else None
        if temporary_parent is not None:
            temporary_parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="taxsentry-restore-",
            dir=temporary_parent,
        ) as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            units_path = Path(temporary) / "units.jsonl"
            analysis_path = Path(temporary) / "analysis.json"
            manifest_object = self.object_store.download(manifest_key, manifest_path)
            units_object = self.object_store.download(units_key, units_path)
            _verify_digest(manifest_object.sha256, manifest_sha256, "manifest")
            _verify_digest(units_object.sha256, units_sha256, "units")
            if analysis_key:
                analysis_object = self.object_store.download(
                    analysis_key,
                    analysis_path,
                )
                _verify_digest(
                    analysis_object.sha256,
                    analysis_sha256,
                    "analysis",
                )
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise DistributedDocumentError(
                    "Distributed document manifest is not valid JSON"
                ) from exc
            if not isinstance(manifest, dict):
                raise DistributedDocumentError(
                    "Distributed document manifest must be an object"
                )
            if (
                str(manifest.get("company_id") or "") != company_id
                or str(manifest.get("case_id") or "") != case_id
                or str(manifest.get("sha256") or "").lower() != sha256
            ):
                raise DistributedDocumentError(
                    "Distributed document manifest scope does not match its job"
                )
            company_namespace = hashlib.sha256(company_id.encode()).hexdigest()[:16]
            expected_raw_key = (
                f"documents/raw/{company_namespace}/{sha256}"
                f"{str(manifest.get('suffix') or '').casefold()}"
            )
            if (
                raw_key != expected_raw_key
                or str(manifest.get("raw_uri") or "") != raw_key
            ):
                raise DistributedDocumentError(
                    "Distributed document raw object scope does not match"
                )
            result_document_id = str(result.get("document_id") or "")
            if result_document_id and result_document_id != str(manifest.get("id") or ""):
                raise DistributedDocumentError(
                    "Distributed document result does not match its manifest"
                )
            manifest["units_uri"] = units_key
            metadata = dict(manifest.get("metadata") or {})
            if metadata.get("extraction") != self.extraction:
                raise DistributedDocumentError(
                    "Distributed document extraction version does not match"
                )
            if (
                str(metadata.get("result_prefix") or "") != result_prefix
                or str(metadata.get("units_object_key") or "") != units_key
                or str(metadata.get("units_sha256") or "") != units_sha256
                or str(metadata.get("analysis_object_key") or "") != analysis_key
                or str(metadata.get("analysis_sha256") or "") != analysis_sha256
            ):
                raise DistributedDocumentError(
                    "Distributed document manifest object lineage does not match"
                )
            metadata["units_object_key"] = units_key
            metadata.pop("analysis_uri", None)
            manifest["metadata"] = metadata
            return self.local_service.restore_manifest(
                manifest,
                units_path,
                analysis_path=analysis_path if analysis_key else None,
            )

    def _ensure_local(self, document_id: str, *, company_id: str):
        try:
            return self.local_service.get_manifest(
                document_id,
                company_id=company_id,
            )
        except KeyError:
            row = self.queue.get_document(
                document_id,
                company_id=company_id,
            )
            if row is None:
                raise
        manifest = row.get("manifest")
        if isinstance(manifest, str):
            try:
                manifest = json.loads(manifest)
            except json.JSONDecodeError as exc:
                raise DistributedDocumentError(
                    "Stored document manifest is not valid JSON"
                ) from exc
        if not isinstance(manifest, Mapping):
            raise DistributedDocumentError("Stored document manifest is missing")
        metadata = _mapping(manifest.get("metadata"))
        result_prefix = str(metadata.get("result_prefix") or "")
        result = {
            "document_id": document_id,
            "company_id": company_id,
            "case_id": str(manifest.get("case_id") or ""),
            "raw_key": str(row.get("raw_object_key") or ""),
            "raw_sha256": str(row.get("sha256") or ""),
            "manifest_key": str(metadata.get("manifest_object_key") or ""),
            "manifest_sha256": str(metadata.get("manifest_sha256") or ""),
            "units_key": str(metadata.get("units_object_key") or ""),
            "units_sha256": str(metadata.get("units_sha256") or ""),
            "analysis_key": str(metadata.get("analysis_object_key") or ""),
            "analysis_sha256": str(metadata.get("analysis_sha256") or ""),
        }
        return self._restore_result(
            result,
            company_id=company_id,
            case_id=str(manifest.get("case_id") or ""),
            sha256=str(row.get("sha256") or ""),
            result_prefix=result_prefix,
        )


def job_queue_from_settings(
    settings: Mapping[str, Any],
    *,
    dsn: str | None = None,
    environ: Mapping[str, str] | None = None,
    secret_getter: Callable[[str], str] | None = None,
) -> PostgresJobQueue:
    environ = os.environ if environ is None else environ
    data_plane = _mapping(settings.get("data_plane"))
    resolved_dsn = (
        (dsn or "").strip()
        or str(environ.get("TAXSENTRY_POSTGRES_DSN") or "").strip()
        or str(data_plane.get("postgres_dsn") or "").strip()
    )
    if resolved_dsn:
        return JobQueue(resolved_dsn)
    password = str(environ.get("TAXSENTRY_POSTGRES_PASSWORD") or "") or _secret(
        "data-plane:postgres-password",
        secret_getter,
    )
    if not password:
        raise ValueError(
            "Configure data_plane.postgres_dsn, TAXSENTRY_POSTGRES_DSN, "
            "or the data-plane:postgres-password keyring secret"
        )
    user = str(
        environ.get("TAXSENTRY_POSTGRES_USER")
        or data_plane.get("postgres_user")
        or "taxsentry"
    )
    host = str(
        environ.get("TAXSENTRY_POSTGRES_HOST")
        or data_plane.get("postgres_host")
        or "localhost"
    )
    if any(character in host for character in "/?#@"):
        raise ValueError("PostgreSQL host contains unsafe URL characters")
    port = int(
        environ.get("TAXSENTRY_POSTGRES_PORT")
        or data_plane.get("postgres_port")
        or 5432
    )
    if not 1 <= port <= 65_535:
        raise ValueError("PostgreSQL port must be between 1 and 65535")
    database = str(
        environ.get("TAXSENTRY_POSTGRES_DB")
        or data_plane.get("postgres_db")
        or "taxsentry"
    )
    sslmode = str(
        environ.get("TAXSENTRY_POSTGRES_SSLMODE")
        or data_plane.get("postgres_sslmode")
        or "require"
    )
    if sslmode not in {
        "disable",
        "allow",
        "prefer",
        "require",
        "verify-ca",
        "verify-full",
    }:
        raise ValueError("Unsupported PostgreSQL sslmode")
    query = urlencode({"sslmode": sslmode})
    resolved_dsn = (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(database, safe='')}?{query}"
    )
    return JobQueue(resolved_dsn)


def object_store_from_settings(
    settings: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    secret_getter: Callable[[str], str] | None = None,
) -> ObjectStore:
    environ = os.environ if environ is None else environ
    data_plane = _mapping(settings.get("data_plane"))
    configured = _mapping(data_plane.get("object_store"))
    kind = str(
        environ.get("TAXSENTRY_OBJECT_STORE")
        or ("s3" if environ.get("TAXSENTRY_S3_ENDPOINT") else "")
        or configured.get("kind")
        or "local"
    ).strip().casefold()
    if kind == "local":
        root = str(
            environ.get("TAXSENTRY_OBJECT_ROOT")
            or configured.get("root")
            or Path.home() / ".taxsentry" / "objects"
        )
        return LocalObjectStore(Path(root))
    if kind != "s3":
        raise ValueError("data_plane.object_store.kind must be local or s3")
    endpoint_url = str(
        environ.get("TAXSENTRY_S3_ENDPOINT")
        or configured.get("endpoint_url")
        or ""
    ).strip()
    bucket = str(
        environ.get("TAXSENTRY_S3_BUCKET")
        or configured.get("bucket")
        or "taxsentry"
    ).strip()
    allow_source: Any = (
        environ["TAXSENTRY_S3_ALLOW_INSECURE"]
        if "TAXSENTRY_S3_ALLOW_INSECURE" in environ
        else configured.get("allow_insecure", False)
    )
    access_key = str(environ.get("TAXSENTRY_S3_ACCESS_KEY") or "") or _secret(
        "data-plane:s3-access-key",
        secret_getter,
    )
    secret_key = str(environ.get("TAXSENTRY_S3_SECRET_KEY") or "") or _secret(
        "data-plane:s3-secret-key",
        secret_getter,
    )
    store = S3ObjectStore(
        endpoint_url=endpoint_url or None,
        bucket=bucket,
        access_key=access_key or None,
        secret_key=secret_key or None,
        region_name=str(
            environ.get("TAXSENTRY_S3_REGION")
            or configured.get("region_name")
            or "us-east-1"
        ),
        allow_insecure=_truthy(allow_source),
        server_side_encryption=str(
            environ.get("TAXSENTRY_S3_ENCRYPTION")
            or configured.get("server_side_encryption")
            or ""
        )
        or None,
    )
    store.ensure_bucket()
    return store


def _required_result_key(result: Mapping[str, Any], name: str) -> str:
    value = result.get(name)
    if not isinstance(value, str) or not value.strip():
        raise DistributedDocumentError(
            f"Distributed document result is missing {name}"
        )
    return value.strip()


def _required_result_sha256(result: Mapping[str, Any], name: str) -> str:
    value = _required_result_key(result, name).casefold()
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise DistributedDocumentError(
            f"Distributed document result has invalid {name}"
        )
    return value


def _scoped_result_key(
    result: Mapping[str, Any],
    name: str,
    prefix: str,
    filename: str,
) -> str:
    key = _required_result_key(result, name)
    if key != f"{prefix}/{filename}":
        raise DistributedDocumentError(
            f"Distributed document result has an invalid {name} scope"
        )
    return key


def _verify_digest(actual: str, expected: str, label: str) -> None:
    if actual != expected:
        raise DistributedDocumentError(
            f"Distributed document {label} SHA-256 verification failed"
        )


def _local_store_is_shared(
    data_plane: Mapping[str, Any],
    environ: Mapping[str, str] | None,
) -> bool:
    values = os.environ if environ is None else environ
    if "TAXSENTRY_OBJECT_LOCAL_SHARED" in values:
        return _truthy(values["TAXSENTRY_OBJECT_LOCAL_SHARED"])
    return _truthy(_mapping(data_plane.get("object_store")).get("shared"))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _truthy(value: Any) -> bool:
    return value is True or (
        isinstance(value, str)
        and value.strip().casefold() in {"1", "true", "yes", "on"}
    )


def _secret(
    name: str,
    getter: Callable[[str], str] | None,
) -> str:
    if getter is not None:
        return getter(name) or ""
    try:
        from taxsentry.secrets import get_secret

        return get_secret(name)
    except Exception:
        return ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
