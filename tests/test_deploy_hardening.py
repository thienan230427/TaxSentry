from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import validate_production_deploy, worker_entrypoint

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_COMPOSE = ROOT / "deploy" / "compose.production.json"


def _write_secret_dir(path: Path) -> None:
    values = {
        "postgres_password": "postgres-strong-value",
        "postgres_dsn": (
            "postgresql://taxsentry:worker-strong-value@postgres:5432/taxsentry"
            "?sslmode=verify-full&sslrootcert=%2Frun%2Fsecrets%2Fpostgres_ca"
        ),
        "postgres_ca.crt": "-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----",
        "postgres.crt": "-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----",
        "postgres.key": "-----BEGIN PRIVATE KEY-----\nZmFrZQ==\n-----END PRIVATE KEY-----",
        "minio_root_user": "root-access-key",
        "minio_root_password": "root-strong-value",
        "minio_ca.crt": "-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----",
        "minio.crt": "-----BEGIN CERTIFICATE-----\nZmFrZQ==\n-----END CERTIFICATE-----",
        "minio.key": "-----BEGIN PRIVATE KEY-----\nZmFrZQ==\n-----END PRIVATE KEY-----",
        "worker_s3_access_key": "worker-access-key",
        "worker_s3_secret_key": "worker-strong-value",
    }
    path.mkdir()
    for name, value in values.items():
        secret = path / name
        secret.write_text(value, encoding="utf-8")
        secret.chmod(0o600)


def test_production_compose_passes_static_hardening_validation() -> None:
    assert validate_production_deploy.validate_compose(PRODUCTION_COMPOSE) == []

    compose = json.loads(PRODUCTION_COMPOSE.read_text(encoding="utf-8"))
    assert compose["networks"]["backend"]["internal"] is True
    assert all("ports" not in service for service in compose["services"].values())


def test_production_validator_rejects_public_ports_and_direct_secrets(tmp_path: Path) -> None:
    compose = json.loads(PRODUCTION_COMPOSE.read_text(encoding="utf-8"))
    compose["services"]["worker"]["ports"] = ["8080:8080"]
    compose["services"]["worker"]["environment"]["TAXSENTRY_POSTGRES_DSN"] = "must-not-leak"
    config_dir = tmp_path / "deploy"
    (config_dir / "postgres").mkdir(parents=True)
    (config_dir / "compose.production.json").write_text(json.dumps(compose), encoding="utf-8")
    (config_dir / "postgres" / "pg_hba.conf").write_text(
        (ROOT / "deploy" / "postgres" / "pg_hba.conf").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    errors = validate_production_deploy.validate_compose(config_dir / "compose.production.json")

    assert "service worker: published ports are forbidden" in errors
    assert "service worker: direct TAXSENTRY_POSTGRES_DSN is forbidden" in errors
    assert "must-not-leak" not in " ".join(errors)


def test_development_compose_remains_local_only() -> None:
    compose = (ROOT / "deploy" / "compose.yml").read_text(encoding="utf-8")
    assert "TAXSENTRY_BIND_HOST:-127.0.0.1" in compose
    assert "TAXSENTRY_POSTGRES_SSLMODE: disable" in compose
    assert "TAXSENTRY_S3_ENDPOINT: http://minio:9000" in compose
    assert 'test: ["CMD", "/usr/local/bin/minio-entrypoint", "healthcheck"]' in compose
    assert compose.count("condition: service_healthy") == 2
    assert "internal: true" in compose
    assert compose.count("- host-access") == 2
    assert "TAXSENTRY_OFFICE_NETWORK_ISOLATED=1" in (
        ROOT / "deploy" / "Dockerfile.worker"
    ).read_text(encoding="utf-8")


def test_secret_directory_validation_checks_tls_and_least_privilege(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    _write_secret_dir(secret_dir)
    assert validate_production_deploy.validate_secret_dir(secret_dir) == []

    (secret_dir / "worker_s3_access_key").write_text("root-access-key", encoding="utf-8")
    (secret_dir / "worker_s3_access_key").chmod(0o600)
    errors = validate_production_deploy.validate_secret_dir(secret_dir)
    assert errors == ["worker S3 access key must differ from the MinIO root user"]
    assert "root-access-key" not in " ".join(errors)


def test_worker_entrypoint_reads_only_allowlisted_secret_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_file = tmp_path / "postgres_dsn"
    secret_file.write_text("postgresql://safe-runtime-value", encoding="utf-8")
    environ = {"TAXSENTRY_POSTGRES_DSN_FILE": str(secret_file)}

    worker_entrypoint.load_secret_environment(environ)

    assert environ == {"TAXSENTRY_POSTGRES_DSN": "postgresql://safe-runtime-value"}
    assert capsys.readouterr() == ("", "")

    environ["TAXSENTRY_POSTGRES_DSN_FILE"] = str(secret_file)
    with pytest.raises(RuntimeError, match="cannot both be set"):
        worker_entrypoint.load_secret_environment(environ)
    assert capsys.readouterr() == ("", "")


def test_images_use_secret_entrypoints_and_runbook_encrypts_backups() -> None:
    worker_dockerfile = (ROOT / "deploy" / "Dockerfile.worker").read_text(encoding="utf-8")
    minio_dockerfile = (ROOT / "deploy" / "Dockerfile.minio").read_text(encoding="utf-8")
    minio_entrypoint = (ROOT / "deploy" / "minio-entrypoint.go").read_text(encoding="utf-8")
    runbook = (ROOT / "deploy" / "PRODUCTION.md").read_text(encoding="utf-8")

    assert 'CMD ["python", "/usr/local/bin/taxsentry-worker"]' in worker_dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/minio-entrypoint"]' in minio_dockerfile
    assert "os.Lstat(file)" in minio_entrypoint
    for command in (
        "set +x",
        "pg_dump",
        "mc --config-dir",
        "object-sha256.txt",
        "age --encrypt",
        "sha256sum -c",
    ):
        assert command in runbook
