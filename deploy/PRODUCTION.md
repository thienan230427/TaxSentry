# TaxSentry 3.0 production data plane

`compose.yml` remains the localhost development stack. Use
`compose.production.json` only after the host, certificates, secret files, and
backup target below have been prepared.

## Host prerequisites

- Keep Docker data, PostgreSQL, MinIO, and backup paths on BitLocker or LUKS
  encrypted volumes. Record the live `manage-bde -status` or `cryptsetup status`
  evidence for every host.
- Permit host-to-host traffic only between approved worker/coordinator
  addresses. The supplied `backend` bridge is internal and publishes no ports;
  multi-host routing must be supplied and tested by the deployment environment.
- Issue certificates from an internal CA. PostgreSQL's certificate must include
  `postgres` and MinIO's certificate must include `minio` in its SANs. Keep
  private keys unencrypted at runtime only inside the encrypted, access-controlled
  secret directory.
- Provision a non-root MinIO access key restricted to the configured TaxSentry
  bucket. It must not equal the MinIO root credential.
- Pin and scan the built images before deployment. Do not run an unreviewed
  document worker image.

Docker Compose file-backed secrets retain host-file ownership on implementations
that cannot apply the long-syntax `uid`, `gid`, and `mode` fields. On Linux,
prepare the files accordingly:

| Files | Owner | Mode |
| --- | ---: | ---: |
| `postgres_password`, `postgres.key` | `999:999` | `0400` |
| `minio_root_user`, `minio_root_password`, `minio.key` | `65532:65532` | `0400` |
| `postgres_dsn`, `worker_s3_access_key`, `worker_s3_secret_key` | `10001:10001` | `0400` |
| `postgres_ca.crt`, `postgres.crt`, `minio_ca.crt`, `minio.crt` | root | `0444` |

The `postgres_dsn` secret must use `sslmode=verify-full` and
`sslrootcert=/run/secrets/postgres_ca`, for example with a URL-encoded password.
Never place a real credential in `.env`, Compose YAML/JSON, shell history, or CI
logs.

## Validate and start

Copy `.env.production.example` to an untracked `.env.production` and set only
non-secret values. Point `TAXSENTRY_SECRET_DIR` at the prepared directory, then:

```bash
set +x
python scripts/validate_production_deploy.py \
  --compose deploy/compose.production.json \
  --secret-dir "$TAXSENTRY_SECRET_DIR"
docker compose --env-file deploy/.env.production \
  -f deploy/compose.production.json config --quiet
docker compose --env-file deploy/.env.production \
  -f deploy/compose.production.json up -d --build
```

After startup, verify on the real network:

1. `psql` succeeds with the CA and `sslmode=verify-full`; a TCP connection with
   `sslmode=disable` is rejected.
2. `mc` trusts MinIO's HTTPS chain and rejects the endpoint when the wrong CA or
   hostname is used.
3. An untrusted peer cannot reach PostgreSQL, MinIO, or the worker network.
4. `docker inspect` confirms read-only roots, dropped capabilities,
   `no-new-privileges`, PID/memory/CPU limits, and no published ports.
5. Trigger a controlled worker failure and inspect centralized logs to confirm
   that DSNs, passwords, access keys, and document contents were not emitted.

## Encrypted backup and restore drill

Run backups on an encrypted volume with `age`, PostgreSQL client tools, and
MinIO Client (`mc`) installed. Prepare these root-readable files through the
host secret manager:

- `/run/secrets/backup-pg-service.conf`: TLS PostgreSQL service definition.
- `/run/secrets/backup-pgpass`: `0600` pgpass file for a least-privilege backup role.
- `/run/secrets/mc-config/config.json`: `0600` MinIO Client configuration for a
  read-only backup identity.
- `/etc/taxsentry/backup-recipients.txt`: one or more public `age` recipients.

The following reference procedure never places a credential in an argument or
log. Keep shell tracing disabled:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077

BACKUP_ROOT=/mnt/encrypted/taxsentry-backups
AGE_RECIPIENTS=/etc/taxsentry/backup-recipients.txt
export PGSERVICEFILE=/run/secrets/backup-pg-service.conf
export PGPASSFILE=/run/secrets/backup-pgpass
MC_CONFIG_DIR=/run/secrets/mc-config

test -d "$BACKUP_ROOT"
test -r "$AGE_RECIPIENTS"
test -r "$PGSERVICEFILE"
test -r "$PGPASSFILE"
test -r "$MC_CONFIG_DIR/config.json"

RUN_DIR="$(mktemp -d "$BACKUP_ROOT/staging.XXXXXX")"
cleanup() {
  if [[ -n "${RUN_DIR:-}" && "$RUN_DIR" == "$BACKUP_ROOT"/staging.* && -d "$RUN_DIR" ]]; then
    find "$RUN_DIR" -xdev -mindepth 1 -delete
    rmdir "$RUN_DIR"
  fi
}
trap cleanup EXIT

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$BACKUP_ROOT/taxsentry-$STAMP.tar.age"
CHECKSUM="$BACKUP_ROOT/taxsentry-$STAMP.tar.age.sha256"

PGSERVICE=taxsentry-backup pg_dump --format=custom --file="$RUN_DIR/postgres.dump"
mkdir "$RUN_DIR/objects"
mc --config-dir "$MC_CONFIG_DIR" mirror --quiet taxsentry/taxsentry "$RUN_DIR/objects"
(
  cd "$RUN_DIR/objects"
  find . -type f -print0 | sort -z | xargs -0 -r sha256sum > "$RUN_DIR/object-sha256.txt"
)
tar -C "$RUN_DIR" -cf - . \
  | age --encrypt --recipients-file "$AGE_RECIPIENTS" > "$ARCHIVE"

(
  cd "$BACKUP_ROOT"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$CHECKSUM")"
  sha256sum -c "$(basename "$CHECKSUM")"
)
```

Do not call the backup complete until a separate restore host has:

1. verified `sha256sum -c`,
2. decrypted with a recovery identity held outside the source host,
3. restored the PostgreSQL dump into a clean database,
4. restored objects into an empty test bucket,
5. verified every restored object against `object-sha256.txt`,
6. compared critical database row counts with the source backup record, and
7. completed a TaxSentry ingest/query smoke test.

Deleting the staging directory is not a substitute for encrypted storage,
especially on SSDs. Retention, off-site replication, key rotation, and restore
frequency are deployment policy and must be exercised on the real infrastructure.

References: [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/),
[Compose build and secret syntax](https://docs.docker.com/reference/compose-file/build/),
and [MinIO server TLS configuration](https://docs.min.io/aistor/reference/aistor-server/).
