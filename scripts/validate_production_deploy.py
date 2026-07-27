from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE = REPO_ROOT / "deploy" / "compose.production.json"
REQUIRED_SECRET_FILES = (
    "postgres_password",
    "postgres_dsn",
    "postgres_ca.crt",
    "postgres.crt",
    "postgres.key",
    "minio_root_user",
    "minio_root_password",
    "minio_ca.crt",
    "minio.crt",
    "minio.key",
    "worker_s3_access_key",
    "worker_s3_secret_key",
)
PRIVATE_SECRET_FILES = {
    "postgres_password",
    "postgres_dsn",
    "postgres.key",
    "minio_root_user",
    "minio_root_password",
    "minio.key",
    "worker_s3_access_key",
    "worker_s3_secret_key",
}
SCALAR_SECRET_FILES = PRIVATE_SECRET_FILES - {"postgres.key", "minio.key"}
PLACEHOLDER_MARKERS = ("change-me", "changeme", "placeholder", "replace-me", "replace_with", "<secret")


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _secret_mounts(service: dict[str, Any]) -> dict[str, str]:
    mounts: dict[str, str] = {}
    for item in _as_list(service.get("secrets")):
        if isinstance(item, str):
            mounts[item] = item
            continue
        secret = _as_mapping(item)
        source = str(secret.get("source", ""))
        if source:
            mounts[source] = str(secret.get("target", source))
    return mounts


def validate_compose(path: Path = DEFAULT_COMPOSE) -> list[str]:
    """Statically validate security invariants without resolving secret values."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [f"{path.name}: cannot read valid JSON"]

    errors: list[str] = []
    services = _as_mapping(document.get("services"))
    for name in ("postgres", "minio", "worker"):
        if name not in services:
            errors.append(f"service {name}: missing")

    backend = _as_mapping(_as_mapping(document.get("networks")).get("backend"))
    if backend.get("internal") is not True:
        errors.append("network backend: must be internal")

    for name, raw_service in services.items():
        service = _as_mapping(raw_service)
        if "ports" in service:
            errors.append(f"service {name}: published ports are forbidden")
        if service.get("read_only") is not True:
            errors.append(f"service {name}: read_only must be true")
        if "ALL" not in _as_list(service.get("cap_drop")):
            errors.append(f"service {name}: cap_drop must contain ALL")
        if "no-new-privileges:true" not in _as_list(service.get("security_opt")):
            errors.append(f"service {name}: no-new-privileges is required")
        if not _as_list(service.get("tmpfs")):
            errors.append(f"service {name}: tmpfs is required")
        if set(_as_list(service.get("networks"))) != {"backend"}:
            errors.append(f"service {name}: only the backend network is allowed")
        for limit in ("cpus", "mem_limit", "pids_limit"):
            if not service.get(limit):
                errors.append(f"service {name}: {limit} is required")

    postgres = _as_mapping(services.get("postgres"))
    postgres_env = _as_mapping(postgres.get("environment"))
    if postgres_env.get("POSTGRES_PASSWORD_FILE") != "/run/secrets/postgres_password":
        errors.append("service postgres: POSTGRES_PASSWORD_FILE is required")
    if "POSTGRES_PASSWORD" in postgres_env:
        errors.append("service postgres: direct POSTGRES_PASSWORD is forbidden")
    expected_postgres_secrets = {
        "postgres_password": "postgres_password",
        "postgres_ca": "postgres_ca",
        "postgres_tls_cert": "postgres_tls_cert",
        "postgres_tls_key": "postgres_tls_key",
    }
    if not expected_postgres_secrets.items() <= _secret_mounts(postgres).items():
        errors.append("service postgres: required secret mounts are incomplete")
    if "./postgres/pg_hba.conf:/etc/postgresql/pg_hba.conf:ro" not in _as_list(
        postgres.get("volumes")
    ):
        errors.append("service postgres: read-only pg_hba.conf mount is required")
    postgres_command = " ".join(str(item) for item in _as_list(postgres.get("command")))
    for setting in (
        "ssl=on",
        "ssl_min_protocol_version=TLSv1.2",
        "ssl_cert_file=/run/secrets/postgres_tls_cert",
        "ssl_key_file=/run/secrets/postgres_tls_key",
        "ssl_ca_file=/run/secrets/postgres_ca",
        "hba_file=/etc/postgresql/pg_hba.conf",
        "password_encryption=scram-sha-256",
        "log_statement=none",
    ):
        if setting not in postgres_command:
            errors.append(f"service postgres: missing {setting}")

    hba_path = path.parent / "postgres" / "pg_hba.conf"
    try:
        hba = hba_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        errors.append("service postgres: pg_hba.conf is unreadable")
    else:
        if not re.search(r"(?m)^\s*hostnossl\s+all\s+all\s+0\.0\.0\.0/0\s+reject\s*$", hba):
            errors.append("service postgres: IPv4 non-TLS rejection is missing")
        if not re.search(r"(?m)^\s*hostnossl\s+all\s+all\s+::/0\s+reject\s*$", hba):
            errors.append("service postgres: IPv6 non-TLS rejection is missing")
        if len(re.findall(r"(?m)^\s*hostssl\s+all\s+all\s+.+\s+scram-sha-256\s*$", hba)) < 2:
            errors.append("service postgres: TLS SCRAM rules are incomplete")

    minio = _as_mapping(services.get("minio"))
    minio_env = _as_mapping(minio.get("environment"))
    for direct, file_name, expected_path in (
        ("MINIO_ROOT_USER", "MINIO_ROOT_USER_FILE", "/run/secrets/minio_root_user"),
        ("MINIO_ROOT_PASSWORD", "MINIO_ROOT_PASSWORD_FILE", "/run/secrets/minio_root_password"),
    ):
        if direct in minio_env:
            errors.append(f"service minio: direct {direct} is forbidden")
        if minio_env.get(file_name) != expected_path:
            errors.append(f"service minio: {file_name} is required")
    minio_command = [str(item) for item in _as_list(minio.get("command"))]
    if not minio_command or minio_command[0] != "server":
        errors.append("service minio: command must start with server")
    if "--certs-dir" not in minio_command or "/run/secrets/minio-certs" not in minio_command:
        errors.append("service minio: TLS certificate directory is required")
    expected_minio_secrets = {
        "minio_root_user": "minio_root_user",
        "minio_root_password": "minio_root_password",
        "minio_ca": "/run/secrets/minio-certs/CAs/root.crt",
        "minio_tls_cert": "/run/secrets/minio-certs/public.crt",
        "minio_tls_key": "/run/secrets/minio-certs/private.key",
    }
    if not expected_minio_secrets.items() <= _secret_mounts(minio).items():
        errors.append("service minio: required secret mounts are incomplete")
    minio_health = _as_mapping(minio.get("healthcheck"))
    if _as_list(minio_health.get("test")) != [
        "CMD",
        "/usr/local/bin/minio-entrypoint",
        "healthcheck",
    ]:
        errors.append("service minio: entrypoint healthcheck is required")

    worker = _as_mapping(services.get("worker"))
    worker_env = _as_mapping(worker.get("environment"))
    for direct in (
        "TAXSENTRY_POSTGRES_DSN",
        "TAXSENTRY_POSTGRES_PASSWORD",
        "TAXSENTRY_S3_ACCESS_KEY",
        "TAXSENTRY_S3_SECRET_KEY",
    ):
        if direct in worker_env:
            errors.append(f"service worker: direct {direct} is forbidden")
    for file_name, expected_path in (
        ("TAXSENTRY_POSTGRES_DSN_FILE", "/run/secrets/postgres_dsn"),
        ("TAXSENTRY_S3_ACCESS_KEY_FILE", "/run/secrets/worker_s3_access_key"),
        ("TAXSENTRY_S3_SECRET_KEY_FILE", "/run/secrets/worker_s3_secret_key"),
    ):
        if worker_env.get(file_name) != expected_path:
            errors.append(f"service worker: {file_name} is required")
    if not str(worker_env.get("TAXSENTRY_S3_ENDPOINT", "")).startswith("https://"):
        errors.append("service worker: S3 endpoint must use HTTPS")
    if str(worker_env.get("TAXSENTRY_S3_ALLOW_INSECURE", "")).lower() != "false":
        errors.append("service worker: insecure S3 transport must be disabled")
    if worker_env.get("AWS_CA_BUNDLE") != "/run/secrets/minio_ca":
        errors.append("service worker: AWS_CA_BUNDLE is required")
    expected_worker_secrets = {
        "postgres_dsn": "postgres_dsn",
        "postgres_ca": "postgres_ca",
        "minio_ca": "minio_ca",
        "worker_s3_access_key": "worker_s3_access_key",
        "worker_s3_secret_key": "worker_s3_secret_key",
    }
    if not expected_worker_secrets.items() <= _secret_mounts(worker).items():
        errors.append("service worker: required secret mounts are incomplete")
    if worker.get("user") != "10001:10001":
        errors.append("service worker: non-root runtime user is required")
    dependencies = _as_mapping(worker.get("depends_on"))
    for dependency in ("postgres", "minio"):
        if _as_mapping(dependencies.get(dependency)).get("condition") != "service_healthy":
            errors.append(
                f"service worker: {dependency} must use service_healthy"
            )

    declared_secrets = _as_mapping(document.get("secrets"))
    for name, raw_secret in declared_secrets.items():
        if not str(_as_mapping(raw_secret).get("file", "")).strip():
            errors.append(f"secret {name}: file source is required")
    for service_name, raw_service in services.items():
        for item in _as_list(_as_mapping(raw_service).get("secrets")):
            source = item if isinstance(item, str) else _as_mapping(item).get("source")
            if not source or source not in declared_secrets:
                errors.append(f"service {service_name}: undeclared secret reference")

    return errors


def validate_secret_dir(path: Path) -> list[str]:
    """Validate secret-file shape and TLS DSN policy without exposing contents."""

    if path.is_symlink() or not path.is_dir():
        return ["secret directory: missing, not a directory, or a symlink"]

    errors: list[str] = []
    values: dict[str, str] = {}
    for name in REQUIRED_SECRET_FILES:
        secret_path = path / name
        if secret_path.is_symlink() or not secret_path.is_file():
            errors.append(f"secret {name}: missing, not a file, or a symlink")
            continue
        try:
            raw = secret_path.read_bytes()
        except OSError:
            errors.append(f"secret {name}: unreadable")
            continue
        limit = 65_536 if name in SCALAR_SECRET_FILES else 1_048_576
        if not raw or len(raw) > limit or b"\x00" in raw:
            errors.append(f"secret {name}: invalid size or content")
            continue
        try:
            value = raw.decode("utf-8").strip()
        except UnicodeError:
            errors.append(f"secret {name}: must be UTF-8 text")
            continue
        if not value:
            errors.append(f"secret {name}: empty")
            continue
        if name in SCALAR_SECRET_FILES and ("\n" in value or "\r" in value):
            errors.append(f"secret {name}: must contain one line")
        if any(marker in value.casefold() for marker in PLACEHOLDER_MARKERS):
            errors.append(f"secret {name}: placeholder value is forbidden")
        if os.name != "nt" and name in PRIVATE_SECRET_FILES:
            if secret_path.stat().st_mode & 0o077:
                errors.append(f"secret {name}: group/world permissions must be removed")
        values[name] = value

    for name in ("postgres_ca.crt", "postgres.crt", "minio_ca.crt", "minio.crt"):
        if name in values and "-----BEGIN CERTIFICATE-----" not in values[name]:
            errors.append(f"secret {name}: PEM certificate marker is missing")
    for name in ("postgres.key", "minio.key"):
        if name in values and not re.search(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----", values[name]):
            errors.append(f"secret {name}: PEM private-key marker is missing")

    dsn = values.get("postgres_dsn")
    if dsn:
        try:
            parsed = urlsplit(dsn)
            query = parse_qs(parsed.query, strict_parsing=True)
            valid_dsn = (
                parsed.scheme in {"postgres", "postgresql"}
                and parsed.hostname == "postgres"
                and bool(parsed.username)
                and bool(parsed.password)
                and query.get("sslmode") == ["verify-full"]
                and query.get("sslrootcert") == ["/run/secrets/postgres_ca"]
            )
        except ValueError:
            valid_dsn = False
        if not valid_dsn:
            errors.append("secret postgres_dsn: must target postgres with verify-full and the mounted CA")

    if values.get("minio_root_user") == values.get("worker_s3_access_key"):
        errors.append("worker S3 access key must differ from the MinIO root user")
    if values.get("minio_root_password") == values.get("worker_s3_secret_key"):
        errors.append("worker S3 secret key must differ from the MinIO root password")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate TaxSentry production deployment inputs.")
    parser.add_argument("--compose", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--secret-dir", type=Path)
    args = parser.parse_args(argv)

    errors = validate_compose(args.compose)
    if args.secret_dir:
        errors.extend(validate_secret_dir(args.secret_dir))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Production deployment validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
