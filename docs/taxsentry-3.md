# TaxSentry 3 development architecture and operations

> [!IMPORTANT]
> This document describes the code currently present on the
> `codex/knowledge-platform-v3` development branch. Python and npm package
> metadata report `3.0.0`; this is not evidence that the release was published
> or that production migration, multi-host security, encrypted backup/restore,
> shadow comparison, or another external release gate has passed.

## Implemented capability map

| Area | Current branch behavior |
| --- | --- |
| Shared agent | Terminal and Telegram use the same serialized `ChatService`; Gmail workflows use the same prompt, document, knowledge, and artifact foundations. |
| Identity and memory | Layered identity files, company-scoped sessions and curated memory, prompt snapshots, session search/resume, deterministic context compression, retention, and content-free forget tombstones are implemented. |
| Document Intelligence | Structural ingestion, unit manifests, coverage reporting, evidence locators, multi-file cases, and workflow/artifact integration are implemented for the formats listed below. |
| Distributed data plane | PostgreSQL with `pgvector`/`pg_trgm`, lease-based jobs, S3-compatible object storage, and a Docker document worker are implemented. When enabled, the shared document facade used by Gmail workflows and artifact generation dispatches document jobs automatically. |
| Jurisdiction knowledge | A verified/freshness-guarded Vietnam pack is bundled. Missing, stale, or unverified packs block legal/tax conclusions while financial analysis remains available. |
| Artifacts | A shared `ArtifactSpec` feeds DOCX, XLSX, PPTX, and PDF renderers with common evidence, assumptions, missing-data, locale, and theme fields. |
| Skills | Local, pinned GitHub, and signed-catalog installation paths stage drafts first. Explicit approval, version history, rollback, and a network-disabled script sandbox are implemented as Python services. |
| Migration | `taxsentry migrate-v3` performs a read-only SQLite backup/export followed by additive, idempotent import and a JSON result report. |
| Multi-host deployment | The queue and object-store clients support shared remote services. The included Compose file is a local development topology, not a production multi-host template. |

## Architecture

```mermaid
flowchart LR
    Channels["Terminal · Telegram · Gmail"] --> Core["Shared TaxSentry agent core"]
    Core --> Prompt["Identity and prompt assembly"]
    Core --> Memory["Sessions and scoped memory"]
    Core --> Documents["Document Intelligence"]
    Core --> Knowledge["Jurisdiction knowledge"]
    Core --> Skills["Governed skills"]
    Core --> Artifacts["ArtifactSpec and renderers"]

    Memory --> AgentStore[("SQLite local or PostgreSQL agent store")]
    Documents --> Coordinator["Configured document coordinator"]
    Coordinator --> LocalObjects[("Local object store")]
    Coordinator --> Queue[("PostgreSQL queue")]
    Knowledge --> Packs["Verified packaged sources"]
    Skills --> SkillFiles["Draft and installed registry"]
    Artifacts --> Outputs["Local output bundles"]
    Queue --> Workers["Docker document workers"]
    Workers --> Documents
    Workers --> Objects[("MinIO or S3-compatible storage")]
```

SQLite remains the default and keeps compatibility workflow state. When
distributed mode is enabled, `runtime_store()` routes company/session/message/
memory operations to PostgreSQL while jobs, reports, deliveries, and related
legacy workflow records remain in SQLite. The configured `DocumentService`
facade used by Gmail workflows and artifact generation uploads raw input,
enqueues a PostgreSQL job, waits for the worker, verifies object hashes and
scope, and restores the result into its local read index. Workers exchange raw
documents, extracted units, deterministic analysis, and manifests through the
configured object store.

## Optional distributed dependencies

The base application does not require PostgreSQL or S3 clients. A source
checkout can install the exact optional dependencies declared in
`pyproject.toml`:

```powershell
uv sync --extra dev --extra distributed
```

For an existing development environment:

```powershell
uv pip install -e ".[distributed]"
```

The `distributed` extra currently pins:

- `psycopg[binary]==3.3.4`
- `boto3==1.43.51`

The Docker worker installs those dependencies directly. The published npm
launcher remains the terminal-first distribution path; use the worker image or
a source environment with the optional extra for direct data-plane APIs.

### PostgreSQL schema groups

`PostgresJobQueue.ensure_schema()` installs `vector` and `pg_trgm`, creates the
`taxsentry` schema, and creates these target groups:

| Group | Tables |
| --- | --- |
| Runtime | `jobs`, `job_steps`, `job_leases`, `job_events`, `deliveries` |
| Company/session | `companies`, `sessions`, `messages`, `session_summaries` |
| Memory | `memory_items`, `memory_tombstones` |
| Documents | `cases`, `documents`, `case_documents`, `document_units` |
| Evidence | `sources`, `claims`, `citations` |
| Knowledge | `jurisdiction_packs`, `knowledge_sources`, `knowledge_chunks` |
| Artifacts | `artifacts`, `artifact_sources` |
| Skills/audit | `skills`, `skill_versions`, `skill_permissions`, `audit_events` |

GIN full-text indexes are created for message, memory, document-unit, and
knowledge text. HNSW vector indexes use the current 1,536-dimension schema for
memory, document-unit, and knowledge embeddings. Creating the schema requires a
database role allowed to install those extensions.

## Identity, prompt, sessions, and memory

### File layout

```text
~/.taxsentry/
├── SOUL.md
├── USER.md
├── MEMORY.md
├── companies/
│   └── <company-id>/
│       ├── COMPANY.md
│       └── MEMORY.md
└── skills/

<repository>/
└── AGENTS.md
```

`PromptAssembler` creates missing writable profile files from packaged defaults.
`AGENTS.md` is read from the repository/project path or the path configured by
`TAXSENTRY_AGENTS_FILE`.

The prompt trust order is fixed:

1. immutable safety rules;
2. `SOUL.md`;
3. runtime guidance and enabled skill metadata;
4. `AGENTS.md`;
5. `USER.md` and the selected `COMPANY.md`;
6. global and company curated-memory snapshots;
7. retrieved memory and the session summary;
8. email, file, web, and tool content wrapped as untrusted data at turn time.

A session stores the assembled system prompt and its SHA-256 hash. Resuming a
session uses that snapshot. `/agent reload` rebuilds the current snapshot and
resets the provider thread; `/new` creates a fresh session and also resets the
provider thread.

### Session commands

The following commands exist in both the terminal and authorized Telegram
gateway:

| Command | Behavior |
| --- | --- |
| `/new` | Archive the prior conversation and start a fresh shared session. |
| `/resume <session-id>` | Resume only if the session belongs to the selected company. |
| `/sessions <query>` | Search that company's saved sessions and messages. |
| `/forget <memory-id>` | Remove one curated-memory payload from the selected company and refresh its Markdown snapshot. |
| `/agent reload` | Reassemble identity, memory, and enabled-skill metadata for the current session. |

The terminal exposes `/skills` for list, local install, pinned-GitHub install,
draft creation, approval, rollback, and disable. Telegram deliberately does not
expose skill installation or approval. `/memory list` and `/company` remain
service/API operations.

### Memory contract

- Every conversation turn is archived with company, platform/source, trust,
  retention, and session metadata.
- Curated memory is stricter than chat history. Automatic curation currently
  requires an explicit trusted-user memory statement such as `hãy nhớ`,
  `ghi nhớ`, `remember`, `quy ước`, or `sở thích`.
- Gmail, extracted documents, websites, and tool output cannot become trusted
  curated memory automatically.
- Secret-like values are rejected or redacted before persistence.
- Retrieval always filters by the selected `company_id`; global curated memory
  may be included, but another company's memory may not.
- Default unpinned retention is 90 days. Pin/unpin exists in the service API;
  it is not yet exposed as a slash command.
- `/forget` deletes the active memory payload and search entry, rewrites the
  Markdown snapshot, and retains only an audit tombstone containing identifiers,
  reason, timestamp, and a content hash.
- Context compression starts at 55% of the configured character window and
  becomes more aggressive at 80%. Recent turns and a deterministic summary are
  retained instead of silently dropping the entire older conversation.

## Document Intelligence

### Accepted input

| Format | Structural coverage |
| --- | --- |
| `.xlsx`, `.xlsm` | Every worksheet, including hidden and very-hidden sheets; row chunks, formulas and cached values, used ranges, merged cells, defined names, chart source formulas, external-link inventory, and formula references. Macros and external links are never executed. |
| `.xls` | Validated legacy compound file converted by the sandboxed LibreOffice path before structural workbook ingestion. |
| `.docx` | Paragraphs, heading/section hierarchy, tables, headers, footers, footnotes, endnotes, comments, tracked-change text, and OCR for embedded images. |
| `.doc` | Validated legacy compound file converted through the sandboxed LibreOffice path. |
| `.pptx` | Slides in natural order, text, tables, chart series, speaker notes, comments, embedded-image OCR, and master/theme metadata. |
| `.ppt` | Validated legacy compound file converted through the sandboxed LibreOffice path. |
| `.pdf` | Per-page direct text, page-selective OCR when text is sparse, tables, images, page metadata, and page/bounding-box evidence locators where available. |
| `.png`, `.jpg`, `.jpeg` | Signature validation and OCR units. |

`.docm` and `.pptm` are not accepted. `.xlsm` is accepted as data, but TaxSentry
does not execute VBA. Legacy Office conversion is allowed only when
`TAXSENTRY_OFFICE_SANDBOX=1`; the supplied worker image sets this flag and uses
an isolated LibreOffice profile with macros disabled.

### Size and coverage contract

- Maximum single document: 500 MB.
- Maximum aggregate size passed to `ingest_case`: 500 MB.
- Open XML expanded-content cap: 4 GiB.
- Archive entry cap: 100,000.
- Maximum archive compression ratio: 1,000.
- Default Excel unit size: 250 rows.
- Default prompt partition size: 60,000 characters.

The synthetic acceptance fixture completed at 522,233,732 bytes (about
498 MiB) in 69.480318 seconds with all 7,609 units processed and none failed or
skipped. The fixture and limitations are recorded in
[the 2026-07-27 benchmark evidence](benchmarks/acceptance-2026-07-27.md).
CPU, RAM, OCR, workbook structure, provider throttling, and object-store
throughput still determine production runtime.

`DocumentService` writes one `DocumentManifest`, a JSONL stream of
`DocumentUnit` records, and a `CoverageReport`. Each structural unit is marked
processed, failed, or skipped. Coverage is complete only when every inventoried
unit is processed and none failed or was skipped. Workflows and artifact
generation consume structural prompt partitions and fail or hold incomplete
coverage instead of truncating raw serialized data silently.

Public API:

```python
from pathlib import Path

from taxsentry.documents import DocumentService

service = DocumentService()
manifest = await service.ingest(
    path=Path("financial-pack.xlsx"),
    company_id="company-a",
    case_id="case-2026-07",
)
units = await service.query(
    document_id=manifest.id,
    company_id="company-a",
    query="doanh thu",
)
coverage = await service.coverage(manifest.id, company_id="company-a")
```

For multiple files, call `ingest_case(paths=..., company_id=..., case_id=...)`.
Document hashes and identifiers preserve source separation; the case reducer
reports conflicts instead of allowing a later file to silently overwrite an
earlier source.

## Evidence and artifacts

Evidence locators are format-specific: Excel sheet/cell ranges, PDF pages and
optional bounding boxes, PowerPoint slides/shapes, Word sections/paragraphs, and
image/page OCR units. The evidence graph is carried into the common
`ArtifactSpec`:

```text
ArtifactSpec
├── metadata, locale, and theme
├── executive_summary and content_blocks
├── datasets, tables, and charts
├── citations
├── assumptions and missing_data
└── provenance
```

DOCX, XLSX, PPTX, and PDF render from this shared specification. A numeric or
legal claim must have evidence or be labeled as an assumption/missing-data item.
This common source is the basis for cross-format parity; it is not permission to
invent a value absent from the source case.

## Jurisdiction packs

The current pack format is a strict JSON-compatible YAML manifest plus content
files. The built-in pack is
`src/taxsentry/knowledge_base/jurisdictions/VN/vietnam-core/pack.yaml`; it
references the bundled Vietnam rules and official-source registry.

At load time, `JurisdictionPack` validates:

- ISO alpha-2 country code, SemVer, languages, currency, and declared domains;
- HTTPS official-source URLs against the pack's exact domain allowlist;
- relative content paths and a SHA-256 checksum over referenced files;
- verification metadata and freshness window.

`JurisdictionRegistry` always permits financial analysis. Legal/tax analysis is
permitted only when the selected country has a verified, fresh pack. A missing
pack produces `missing_knowledge`; an unverified or stale pack produces
`unverified_or_stale`. The workflow and artifact guard remove unsupported legal
claims and route the result for review.

Retrieval combines exact-reference matching, token/full-text relevance, optional
semantic-vector similarity, and trust/freshness/jurisdiction weights. If no
embedding vector is available, deterministic lexical retrieval remains
available. Refresh is exposed through `KnowledgeService.refresh_pack`; custom
non-Vietnam refresh requires a supplied source refresher. The current branch
does not provide a country-pack marketplace command.

## Governed skills

Every `SKILL.md` must start with YAML frontmatter containing:

```yaml
name:
version:
description:
author:
platforms:
jurisdictions:
capabilities:
permissions:
dependencies:
source:
checksum:
signature:
minimum_taxsentry_version:
```

The service supports:

- a validated local folder;
- a GitHub HTTPS repository pinned to a full 40-character commit plus an
  independently supplied checksum;
- a marketplace item from a catalog whose signature has been verified by a
  caller-supplied verifier.

All installs land under `skills/.drafts` and remain disabled. Only
`SkillService.approve(name, version, approved_by=...)` moves a validated version
to the installed registry and enables it. Rollback can select only a previously
approved version. Agent-created skills use `create_draft`, are limited to 256
files/10 MB, require declared permissions/signature fields, and cannot enable
themselves.

The prompt receives only name, version, and description metadata for the enabled
version. A draft or disabled skill is not exposed in prompt assembly.

Script execution uses a digest-pinned container image with:

- `--network=none`;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- non-root user, PID, memory, CPU, timeout, and small `tmpfs` limits;
- only declared filesystem mounts.

A skill requesting network domains is currently rejected because no
domain-enforcing egress runner is implemented. Remote Python code is never
imported into the TaxSentry process.

The terminal `/skills` command wraps these `SkillService` operations. Remote
channels do not receive a skill-management command.

## Local Docker Compose

The repository includes:

- `deploy/compose.yml`
- `deploy/Dockerfile.worker`
- `deploy/Dockerfile.minio`

Start the local development topology from the repository root:

```powershell
$env:POSTGRES_PASSWORD = 'replace-with-a-long-local-password'
$env:MINIO_ROOT_USER = 'taxsentry-local'
$env:MINIO_ROOT_PASSWORD = 'replace-with-another-long-local-password'
$env:TAXSENTRY_JOB_HANDLER = 'taxsentry.data_plane.document_worker:handle_document_job'
docker compose -f deploy/compose.yml up --build
```

Stop it without deleting the named data volumes:

```powershell
docker compose -f deploy/compose.yml down
```

By default, PostgreSQL and MinIO bind only to `127.0.0.1`. The worker is
read-only, non-root, capability-free, and resource-limited. It initializes the
PostgreSQL schema, creates the object bucket when needed, claims jobs through
`FOR UPDATE SKIP LOCKED`, heartbeats its lease, and checkpoints document steps.

> [!WARNING]
> The local Compose worker explicitly uses PostgreSQL `sslmode=disable`, an
> `http://` MinIO endpoint, `TAXSENTRY_S3_ALLOW_INSECURE=true`, and MinIO root
> credentials. Do not expose or copy this topology unchanged to a LAN, WAN, or
> production environment.

## Production multi-host requirements

The current code can connect multiple identical workers to shared PostgreSQL and
MinIO/S3 endpoints, but production networking, certificates, secret
distribution, monitoring, and backup infrastructure are operator
responsibilities. A production deployment must, at minimum:

1. Use PostgreSQL TLS with certificate verification, for example a DSN using
   `sslmode=verify-full` and the correct CA configuration. Never use the local
   Compose `sslmode=disable`.
2. Use an HTTPS MinIO/S3 endpoint. Leave
   `TAXSENTRY_S3_ALLOW_INSECURE` unset/false.
3. Give workers scoped service credentials, not MinIO root credentials. Deliver
   credentials through an OS keyring, Docker secrets, or an approved secret
   manager; do not commit them or place them in the image.
4. Keep PostgreSQL, object storage, and the MinIO console on private networks
   behind firewalls. Add explicit worker egress restrictions; the development
   Compose network is not an internet egress allowlist.
5. Run the same reviewed, digest-pinned worker image on every host and assign a
   unique `TAXSENTRY_WORKER_ID` when stable host identity is required.
6. Encrypt database/object-store volumes with BitLocker, LUKS, or an equivalent
   platform control. Encrypt, test, and rotate backups independently.
7. Configure server-side object encryption where the S3 service supports it
   (`TAXSENTRY_S3_ENCRYPTION`) and manage KMS keys outside TaxSentry.
8. Collect queue, lease, retry, coverage, audit, storage, and delivery telemetry;
   alert on expired leases and repeated unit failures.
9. Keep the worker's CPU, RAM, PID, temporary-space, and execution-time limits
   appropriate for the accepted document fixture set.

No Kubernetes manifests, production certificate automation, or turnkey
multi-host orchestrator are included in this branch.

## SQLite migration

### What the APIs do

`export_sqlite_snapshot` opens the SQLite source read-only, makes a consistent
snapshot, exports every source table as permission-restricted JSONL, and writes
a manifest containing row counts and SHA-256 hashes.

`migrate_sqlite_database` is additive and uses conflict-safe inserts. It imports
the supported v2 groups:

- companies;
- jobs;
- sessions, summaries, and messages;
- reports as legacy artifacts;
- job/global events;
- deliveries;
- attachments as document objects when an object store is supplied.

The source SQLite database is never deleted or modified. Re-running the importer
reports existing rows as skipped. Missing files and broken relationships are
reported as conflicts. Passing no object store produces metadata-only legacy
report artifacts and skips attachment binaries.

There is also a narrower `migrate_sqlite_jobs` compatibility helper. Prefer
`migrate_sqlite_database` for a rehearsed full supported-table import.

### Migration CLI

The command uses the configured data-plane factories; it does not accept a DSN
on the command line where credentials could leak through shell history or the
process list.

Configure PostgreSQL through `data_plane.postgres_dsn`,
`TAXSENTRY_POSTGRES_DSN`, or the discrete PostgreSQL settings/keyring secret
supported by `job_queue_from_settings`. Configure local or S3/MinIO storage
through `data_plane.object_store` and its corresponding environment/keyring
values.

Run a rehearsal with an explicit protected backup directory:

```powershell
$env:TAXSENTRY_POSTGRES_DSN = 'postgresql://taxsentry:REDACTED@db.internal:5432/taxsentry?sslmode=verify-full'
$env:TAXSENTRY_OBJECT_STORE = 's3'
$env:TAXSENTRY_S3_ENDPOINT = 'https://minio.internal'
$env:TAXSENTRY_S3_BUCKET = 'taxsentry'
taxsentry migrate-v3 `
  --sqlite "$env:USERPROFILE\.taxsentry\taxsentry.db" `
  --backup-dir "D:\ProtectedBackups\taxsentry-v3-rehearsal" `
  --company-id "default"
```

Use a secret manager or protected process environment for real credentials; do
not paste a live password into source control or a saved script.

If omitted, `--sqlite` uses the configured TaxSentry SQLite path,
`--backup-dir` creates a unique UTC-stamped directory under
`~/.taxsentry/migration-backups`, and `--company-id` uses the active company.
An explicitly supplied backup directory must be empty.

The command:

1. resolves the PostgreSQL target and fails clearly before work begins when it
   is missing;
2. creates the transactionally consistent hashed SQLite export;
3. ensures the PostgreSQL schema;
4. resolves/initializes the configured object store;
5. performs the additive import without changing the SQLite source;
6. writes `migration-report.json` next to the backup manifest.

Exit code `0` means the migration completed with no conflicts, `1` means it
completed and the report contains conflicts requiring reconciliation, and `2`
means configuration, backup, schema, object-store, or import failed. Existing
rows reported as `skipped` are expected during an idempotency rehearsal.

### Python API equivalent

The CLI is a thin wrapper around the following API. A maintenance environment
using it directly must have the `distributed` extra:

```python
import os
from pathlib import Path

from taxsentry.data_plane import PostgresJobQueue, S3ObjectStore
from taxsentry.data_plane.migration import (
    export_sqlite_snapshot,
    migrate_sqlite_database,
    write_migration_report,
)

source_db = Path(os.environ["TAXSENTRY_V2_SQLITE"]).resolve(strict=True)
backup_dir = Path(os.environ["TAXSENTRY_MIGRATION_DIR"]).resolve()
queue = PostgresJobQueue(os.environ["TAXSENTRY_POSTGRES_DSN"])
queue.ensure_schema()

store = S3ObjectStore(
    bucket=os.environ["TAXSENTRY_S3_BUCKET"],
    endpoint_url=os.environ["TAXSENTRY_S3_ENDPOINT"],
    access_key=os.environ["TAXSENTRY_S3_ACCESS_KEY"],
    secret_key=os.environ["TAXSENTRY_S3_SECRET_KEY"],
    allow_insecure=os.environ.get("TAXSENTRY_S3_ALLOW_INSECURE", "").lower()
    in {"1", "true", "yes"},
    server_side_encryption=os.environ.get("TAXSENTRY_S3_ENCRYPTION") or None,
)
store.ensure_bucket()

manifest = export_sqlite_snapshot(source_db, backup_dir)
report = migrate_sqlite_database(
    source_db,
    queue,
    company_id=os.environ.get("TAXSENTRY_COMPANY_ID", "default"),
    object_store=store,
)
write_migration_report(report, backup_dir / "migration-report.json")
print(f"snapshot manifest: {manifest}")
print(report)
```

Before cutover, compare source row counts with the snapshot manifest and the
per-table `imported`, `skipped`, `conflicts`, and `object_refs` report. Verify
sample object hashes by downloading them from the target store. Run the same
script twice in rehearsal to prove idempotency for the actual source shape.

### Rollback

Migration does not provide an automatic rollback command. The rollback asset is
the untouched SQLite database plus its hashed export and the retained 2.0.13
runtime/package:

1. stop producers and distributed workers;
2. preserve the PostgreSQL and object-store state for investigation;
3. point the retained 2.0.13 runtime back to the original
   `TAXSENTRY_HOME`/`TAXSENTRY_MEMORY_DB`;
4. verify the local profile, provider, Gmail marker, and delivery state before
   resuming work;
5. reconcile work accepted after cutover manually before any external
   redelivery.

Objects created only after cutover are not automatically copied back into
SQLite. Do not resume both versions as active producers against the same Gmail
account or delivery channels.

## Release evidence

The following development evidence was recorded on 2026-07-27:

- Ruff passed for `src`, `tests`, and `scripts`; the local Python 3.12 suite
  passed 231 tests with seven environment-gated skips.
- A live development PostgreSQL/MinIO run passed four queue, agent-store,
  object-store, and lease-recovery tests. A three-worker run also passed the
  distributed document roundtrip and SQLite snapshot migration tests.
- The final worker source passed checkpoint/resume unit tests and was rebuilt
  as a read-only, network-disabled smoke container reporting `3.0.0`.
- `uv lock --check`, Python sdist/wheel build, npm typecheck, four npm tests,
  `npm pack --dry-run --json`, and isolated npm smoke-install passed.
- The synthetic 498 MiB acceptance case completed 7,609/7,609 inventoried units
  in 69.480318 seconds with no silent loss. The result and its SHA-256 are
  retained in
  [the acceptance record](benchmarks/acceptance-2026-07-27.md).

These checks do not replace the remaining external release gates:

- cross-platform CI validation on Python 3.11-3.13;
- production-shaped migration and rollback rehearsal;
- multi-host TLS, scoped credentials, encrypted volumes/backups, and restore
  verification;
- shadow comparison of 2.0.13 and 3.0 artifacts;
- reviewable milestone commits, branch CI, and approval of the draft PR.

Do not tag or merge `3.0.0` until those external gates have retained evidence.
