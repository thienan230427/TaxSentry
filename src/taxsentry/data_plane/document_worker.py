from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any

from taxsentry.gmail import ALLOWED_MIME

from .object_store import LocalObjectStore, ObjectStore, S3ObjectStore
from .queue import LostLeaseError
from .worker import JobContext


def handle_document_job(context: JobContext) -> dict[str, Any]:
    """Environment-configured handler for `taxsentry.data_plane.worker`."""
    return process_document_job(
        context,
        object_store=_object_store_from_env(),
        work_root=_work_root(),
    )


def process_document_job(
    context: JobContext,
    *,
    object_store: ObjectStore,
    work_root: Path | None = None,
    document_service=None,
) -> dict[str, Any]:
    payload = context.job.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Document job payload must be an object")
    object_key = _required_text(payload, "object_key")
    company_id = _required_text(payload, "company_id")
    job_company_id = str(context.job.get("company_id") or "").strip()
    if job_company_id and company_id != job_company_id:
        raise ValueError("Document job company scope does not match its payload")
    if not company_id:
        raise ValueError("Document job requires company_id")
    case_id = _required_text(payload, "case_id")
    job_case_id = str(context.job.get("case_id") or "").strip()
    if job_case_id and case_id != job_case_id:
        raise ValueError("Document job case scope does not match its payload")
    expected_sha256 = _required_sha256(payload, "sha256")
    request_digest = _required_sha256(payload, "request_digest")
    result_prefix = _required_text(payload, "result_prefix").rstrip("/")
    if result_prefix != f"documents/results/{request_digest}":
        raise ValueError("Document result prefix does not match its request")
    extraction = payload.get("extraction")
    if not isinstance(extraction, dict):
        raise ValueError("Document job requires extraction settings")
    from taxsentry.documents import (
        DOCUMENT_EXTRACTION_SCHEMA_VERSION,
        EXCEL_ROWS_PER_UNIT,
    )

    schema_version = int(extraction.get("schema_version") or 0)
    if schema_version != DOCUMENT_EXTRACTION_SCHEMA_VERSION:
        raise ValueError("Unsupported document extraction schema version")
    excel_rows_per_unit = int(
        extraction.get("excel_rows_per_unit") or EXCEL_ROWS_PER_UNIT
    )
    if excel_rows_per_unit < 1:
        raise ValueError("excel_rows_per_unit must be positive")
    languages = payload.get("languages") or ["vie", "eng"]
    if not isinstance(languages, list) or not all(
        isinstance(language, str) and language.strip() for language in languages
    ):
        raise ValueError("languages must be a non-empty list of strings")
    suffix = PurePosixPath(object_key).suffix.casefold()
    if not suffix:
        raise ValueError("Document object key must retain a file extension")
    company_namespace = hashlib.sha256(company_id.encode()).hexdigest()[:16]
    if object_key != f"documents/raw/{company_namespace}/{expected_sha256}{suffix}":
        raise ValueError("Document raw object key does not match its scope")
    source_name = str(payload.get("name") or f"source{suffix}").strip()
    if (
        not source_name
        or "/" in source_name
        or "\\" in source_name
        or PurePosixPath(source_name).suffix.casefold() != suffix
    ):
        raise ValueError("Document job name must be a safe file name matching object_key")
    resumed = _completed_result(
        context,
        object_store,
        company_id=company_id,
        case_id=case_id,
        raw_key=object_key,
        raw_sha256=expected_sha256,
        result_prefix=result_prefix,
    )
    if resumed is not None:
        return resumed

    work_root = (work_root or _work_root()).expanduser().resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"job-{context.id[:8]}-", dir=work_root) as temporary:
        temporary_root = Path(temporary)
        source = temporary_root / source_name
        _ensure_active(context)
        downloaded = object_store.download(object_key, source)
        if downloaded.sha256 != expected_sha256:
            raise ValueError("Downloaded document SHA-256 does not match its job")
        context.checkpoint(
            "download",
            {"object_key": object_key, "sha256": downloaded.sha256},
            processed=1,
            total=1,
            state="completed",
        )

        if document_service is None:
            from taxsentry.documents import DocumentService

            def progress(unit, count):
                if count == 1 or count % 25 == 0:
                    _ensure_active(context)
                    context.checkpoint(
                        "extract",
                        {
                            "document_id": unit.document_id,
                            "last_unit": unit.id,
                            "locator": unit.locator,
                        },
                        processed=count,
                        total=count,
                    )

            document_service = DocumentService(
                temporary_root / "documents",
                excel_rows_per_unit=excel_rows_per_unit,
                progress_callback=progress,
            )
        manifest = document_service.ingest_sync(
            path=source,
            company_id=company_id,
            case_id=case_id,
            languages=[language.strip() for language in languages],
        )
        if manifest.sha256 != expected_sha256:
            raise ValueError("Extracted manifest SHA-256 does not match its job")
        _ensure_active(context)
        context.checkpoint(
            "extract",
            {
                "document_id": manifest.id,
                "processed": manifest.coverage.processed,
                "failed": manifest.coverage.failed,
            },
            processed=manifest.coverage.processed,
            total=manifest.coverage.total,
            state="completed",
        )

        units_key = f"{result_prefix}/units.jsonl"
        manifest_key = f"{result_prefix}/manifest.json"
        analysis_key = f"{result_prefix}/analysis.json"
        units_object = object_store.put_file(units_key, Path(manifest.units_uri))
        analysis_path = Path(str(manifest.metadata.get("analysis_uri") or ""))
        analysis_object = (
            object_store.put_file(analysis_key, analysis_path)
            if analysis_path.is_file()
            else None
        )
        portable_manifest = asdict(manifest)
        portable_manifest["raw_uri"] = object_key
        portable_manifest["units_uri"] = units_key
        portable_metadata = dict(portable_manifest.get("metadata") or {})
        portable_metadata["units_object_key"] = units_key
        portable_metadata["units_sha256"] = units_object.sha256
        portable_metadata["result_prefix"] = result_prefix
        portable_metadata["extraction"] = dict(extraction)
        if analysis_object:
            portable_metadata["analysis_object_key"] = analysis_key
            portable_metadata["analysis_sha256"] = analysis_object.sha256
        portable_metadata.pop("analysis_uri", None)
        portable_manifest["metadata"] = portable_metadata
        manifest_object = object_store.put_bytes(
            manifest_key,
            (
                json.dumps(portable_manifest, ensure_ascii=False, indent=2, default=str)
                + "\n"
            ).encode(),
        )
        database_manifest = {
            **portable_manifest,
            "metadata": {
                **portable_metadata,
                "manifest_object_key": manifest_key,
                "manifest_sha256": manifest_object.sha256,
            },
        }
        persisted = context.persist_document(
            database_manifest,
            _iter_units(Path(manifest.units_uri)),
            raw_object_key=object_key,
            units_object_key=units_key,
            mime_type=next(
                (
                    value
                    for value in ALLOWED_MIME.get(suffix, ())
                    if value != "application/octet-stream"
                ),
                None,
            )
            or mimetypes.guess_type(manifest.name)[0]
            or "application/octet-stream",
        )
        context.checkpoint(
            "persist",
            {
                "document_id": persisted["document_id"],
                "manifest_key": manifest_key,
                "units_key": units_key,
                "analysis_key": analysis_key if analysis_object else "",
                "unit_count": persisted["unit_count"],
            },
            processed=1,
            total=1,
            state="completed",
        )
        result = {
            "document_id": persisted["document_id"],
            "company_id": company_id,
            "case_id": case_id,
            "raw_key": object_key,
            "raw_sha256": downloaded.sha256,
            "manifest_key": manifest_key,
            "manifest_sha256": manifest_object.sha256,
            "units_key": units_key,
            "units_sha256": units_object.sha256,
            "analysis_key": analysis_key if analysis_object else "",
            "analysis_sha256": analysis_object.sha256 if analysis_object else "",
            "coverage": asdict(manifest.coverage),
        }
        context.checkpoint(
            "result",
            result,
            processed=1,
            total=1,
            state="completed",
        )
        return result


def _object_store_from_env() -> ObjectStore:
    backend = os.environ.get("TAXSENTRY_OBJECT_STORE", "").strip().casefold()
    if not backend:
        backend = "s3" if os.environ.get("TAXSENTRY_S3_ENDPOINT") else "local"
    if backend == "local":
        root = os.environ.get("TAXSENTRY_OBJECT_ROOT", "").strip()
        if not root:
            raise ValueError("TAXSENTRY_OBJECT_ROOT is required for the local object store")
        return LocalObjectStore(Path(root))
    if backend != "s3":
        raise ValueError("TAXSENTRY_OBJECT_STORE must be local or s3")
    bucket = os.environ.get("TAXSENTRY_S3_BUCKET", "").strip()
    if not bucket:
        raise ValueError("TAXSENTRY_S3_BUCKET is required for S3/MinIO")
    store = S3ObjectStore(
        endpoint_url=os.environ.get("TAXSENTRY_S3_ENDPOINT") or None,
        bucket=bucket,
        access_key=os.environ.get("TAXSENTRY_S3_ACCESS_KEY") or None,
        secret_key=os.environ.get("TAXSENTRY_S3_SECRET_KEY") or None,
        allow_insecure=_truthy(os.environ.get("TAXSENTRY_S3_ALLOW_INSECURE", "")),
        server_side_encryption=os.environ.get("TAXSENTRY_S3_ENCRYPTION") or None,
    )
    store.ensure_bucket()
    return store


def _work_root() -> Path:
    configured = os.environ.get("TAXSENTRY_WORK_DIR", "").strip()
    if configured:
        return Path(configured)
    container_work = Path("/work")
    return container_work if container_work.is_dir() else Path(tempfile.gettempdir())


def _ensure_active(context: JobContext) -> None:
    if context.cancelled():
        raise LostLeaseError(f"Job {context.id} was cancelled")


def _completed_result(
    context: JobContext,
    object_store: ObjectStore,
    *,
    company_id: str,
    case_id: str,
    raw_key: str,
    raw_sha256: str,
    result_prefix: str,
) -> dict[str, Any] | None:
    steps = getattr(context, "steps", None)
    if not callable(steps):
        return None
    for step in reversed(steps()):
        if step.get("name") != "result" or step.get("state") != "completed":
            continue
        result = step.get("checkpoint")
        if not isinstance(result, dict):
            return None
        manifest_key = str(result.get("manifest_key") or "")
        units_key = str(result.get("units_key") or "")
        analysis_key = str(result.get("analysis_key") or "")
        if (
            str(result.get("company_id") or "") != company_id
            or str(result.get("case_id") or "") != case_id
            or str(result.get("raw_key") or "") != raw_key
            or str(result.get("raw_sha256") or "") != raw_sha256
            or manifest_key != f"{result_prefix}/manifest.json"
            or units_key != f"{result_prefix}/units.jsonl"
            or (analysis_key and analysis_key != f"{result_prefix}/analysis.json")
            or not object_store.exists(manifest_key)
            or not object_store.exists(units_key)
            or (analysis_key and not object_store.exists(analysis_key))
        ):
            return None
        return result
    return None


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Document job requires {key}")
    return value.strip()


def _required_sha256(payload: dict[str, Any], key: str) -> str:
    value = _required_text(payload, key).casefold()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"Document job requires a valid {key}")
    return value


def _iter_units(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                unit = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid document unit JSON at line {line_number}") from exc
            if not isinstance(unit, dict):
                raise ValueError(f"Document unit at line {line_number} must be an object")
            yield unit


def _truthy(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}
