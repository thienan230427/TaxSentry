<div align="center">

# TaxSentry

### Financial Sentinel for Vietnamese business, reporting, and tax workflows

**A terminal-first AI agent that connects conversations, Gmail, financial documents, generated office files, PDF reports, and Telegram in one local workspace.**

[![npm](https://img.shields.io/npm/v/taxsentry?logo=npm&label=npm)](https://www.npmjs.com/package/taxsentry)
[![CI](https://img.shields.io/github/actions/workflow/status/thienan230427/TaxSentry/cross-platform.yml?branch=main&logo=githubactions&label=build)](https://github.com/thienan230427/TaxSentry/actions/workflows/cross-platform.yml)
[![Python](https://img.shields.io/badge/Python-3.11--3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-%E2%89%A522-339933?logo=nodedotjs&logoColor=white)](https://nodejs.org/)
[![License](https://img.shields.io/github/license/thienan230427/TaxSentry)](LICENSE)

[Quick start](#quick-start) · [Features](#features) · [Setup](#interactive-setup) · [Commands](#command-reference) · [Architecture](#architecture) · [TaxSentry 3 operations](docs/taxsentry-3.md) · [Troubleshooting](#troubleshooting)

</div>

> [!IMPORTANT]
> TaxSentry assists with extraction, analysis, and reporting. It does not file taxes or make financial, legal, or operational decisions. A qualified person should verify material conclusions against the original evidence before acting on them.

> [!NOTE]
> The `codex/knowledge-platform-v3` branch contains the TaxSentry 3 development architecture and `3.0.0` package metadata. This does not mean the release has been published or that all release gates have passed. See [TaxSentry 3 development architecture and operations](docs/taxsentry-3.md).

## Overview

TaxSentry is a local, terminal-first assistant for Vietnamese financial and business workflows. It can chat through an AI provider, search Gmail, process new attachments, extract data from office documents and scans, generate polished files, create structured PDF reports, and deliver results through Gmail and Telegram.

The npm package contains a small TypeScript launcher and the matching Python application wheel. On first use, the launcher creates an isolated Python environment under `~/.taxsentry/runtime/venv`, installs the bundled core, and forwards commands to it. The default profile keeps application data local and credentials in the OS keyring. When the optional distributed data plane is configured, documents and metadata are sent to the explicitly configured PostgreSQL and MinIO/S3 services and must be protected as described in the operations guide.

```mermaid
flowchart LR
    subgraph Inputs
        Terminal["Terminal conversation"]
        Gmail["Gmail messages and attachments"]
        Files["Local documents"]
        TelegramIn["Authorized Telegram chat"]
    end

    subgraph TaxSentry
        TUI["Financial Sentinel TUI"]
        Agent["Shared AI agent"]
        Workflow["Document workflow"]
        Extract["Structural Document Intelligence"]
        Store[("SQLite workflow compatibility")]
        AgentStore[("SQLite or PostgreSQL agent state")]
        Coordinator["Configured document coordinator"]
        Queue[("PostgreSQL job leases")]
        DistributedWorker["Docker document worker"]
        Objects[("MinIO or S3 objects")]
        Artifacts["DOCX, XLSX, PPTX, and PDF builder"]
    end

    Terminal --> TUI --> Agent
    TelegramIn --> Agent
    Agent <--> AgentStore
    Gmail --> Workflow --> Extract --> Agent
    Files --> Artifacts
    Gmail --> Artifacts
    Agent --> Artifacts
    Workflow <--> Store
    Workflow --> Extract
    Extract --> Coordinator --> Queue --> DistributedWorker
    DistributedWorker --> Extract
    DistributedWorker <--> Objects
    Artifacts --> TelegramOut["Telegram delivery"]
    Workflow --> GmailOut["Gmail advisory bundle"]
    Workflow --> TelegramOut
```

## Features

### Terminal AI workspace

- Streaming chat inside a Textual-based terminal interface.
- Vietnamese and English interface modes selected during setup.
- Slash-command completion, recent jobs, current integration state, and session controls.
- One serialized chat service shared by the terminal and Telegram gateway.
- Company-scoped conversation history, prompt snapshots, session search/resume, and curated memory. SQLite is the local default; PostgreSQL stores sessions and memory when the distributed data plane is enabled.
- Layered `SOUL.md`, `USER.md`, `MEMORY.md`, `COMPANY.md`, and repository `AGENTS.md` prompt assembly.
- Safe cancellation and clean shutdown of background services.

### Gmail search and automation

- Natural-language Gmail questions in Vietnamese or English.
- Explicit Gmail search syntax through `/gmail search <query>`.
- Full message reading through `/gmail read <uid>`.
- Confirmation before processing manually searched historical messages.
- Automatic polling for new messages with supported attachments after the setup marker.
- Coverage of Gmail All Mail, Spam, and Trash when those mailboxes are available; Sent and Drafts are excluded.
- Gmail labels for `Processing`, `Completed`, `NeedsReview`, and `Failed` workflow states.
- Reports are sent back to the connected Gmail account.

TaxSentry supports messages from every sender. Automatic processing starts only after the per-mailbox UID markers captured during setup, so existing mailbox history is not processed unexpectedly. Historical searches remain available and require an explicit `/gmail process` confirmation.

### Document extraction and reporting

- Structural manifests, unit-level evidence locators, and explicit processed/failed/skipped coverage.
- Full worksheet inventory for XLSX and XLSM, including hidden sheets, formulas, merged ranges, defined names, chart sources, and external-link inventory.
- Structural DOCX and PPTX extraction, including tables, hierarchy, notes/comments, chart data, headers/footers, and embedded-image OCR where supported.
- Per-page PDF text extraction with page-selective OCR for mixed text/scan files.
- OCR for PNG, JPG, and JPEG with configurable language packs.
- Legacy DOC, XLS, and PPT conversion through the sandbox-enabled LibreOffice worker path.
- Multi-file cases up to 500 MB aggregate, with source separation and conflict reporting.
- Advisory Schema v2 reports with grounded metrics, findings, scenarios, tax risks, actionable recommendations, sources, assumptions, and confidence.
- Deterministic Python calculations for growth, budget variance, margins, cost ratios, and three-case P&L sensitivity.
- Official-source legal knowledge freshness checks; stale or unsupported conclusions are held for review.
- Multi-file report bundles and auditable job, report, attachment, delivery, and event records.
- Retry with bounded backoff, per-stage timeouts, cancellation, and duplicate-work protection.
- Channel-aware delivery retries: if Gmail succeeds and Telegram fails, only the failed delivery is retried.

### Artifact generation

TaxSentry can create new office documents directly from a prompt, selected Gmail messages, or local files:

| Output | Command type | Optional template |
| --- | --- | --- |
| Word document | DOCX | `.docx` |
| Spreadsheet | XLSX | `.xlsx` |
| Presentation | PPTX | `.pptx` |
| Report document | PDF | Not applicable |

Generated files use Vietnamese business conventions by default, including VND and `dd/mm/yyyy`. The agent is instructed not to invent missing values and to identify incomplete evidence. Outputs are saved under `~/.taxsentry/outputs` and sent to configured Telegram chats when automatic artifact delivery is enabled.

When no format is specified, TaxSentry selects one of five advisory profiles: CFO brief, tax-risk memo, cash-flow advisory, performance review, or scenario plan. Excel advisory models include source data, editable assumptions, application-generated formulas, a two-variable sensitivity matrix, risks, actions, and charts.

### AI providers

| Provider | How it connects | Best for |
| --- | --- | --- |
| **Codex / ChatGPT** | Official Codex App Server with browser or device-code authentication | Hosted models and Codex accounts |
| **LM Studio** | OpenAI-compatible local endpoint, default `http://127.0.0.1:1234/v1` | Local and private model execution |

Codex uses an isolated home at `~/.taxsentry/codex`. LM Studio models are discovered from the configured endpoint, with a manual model-ID fallback.

### Telegram gateway

- Only chat IDs saved in `director.telegram_chat_ids` are authorized.
- Plain text uses the same assistant and session service as the terminal.
- Gmail search, document creation, job status, retry, approval, cancellation, and latest-report commands are available.
- Generated files and completed Gmail reports can be delivered to every configured chat.
- Telegram Bot API document delivery is limited to 50 MB.

## Quick start

### 1. Install prerequisites

- [Node.js 22 or later](https://nodejs.org/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Python 3.11, 3.12, or 3.13 available to `uv`
- Codex CLI or a running LM Studio server

Optional components:

- Tesseract OCR with `vie` and `eng` language data for images and scanned PDFs.
- LibreOffice for legacy `.doc`, `.xls`, and `.ppt` files.
- Docker with PostgreSQL/pgvector and MinIO for the optional distributed document plane.
- Gmail App Password for Email Agent or Full Agent mode.
- Telegram bot token for Full Agent mode.

### 2. Install TaxSentry

```powershell
npm install -g taxsentry
taxsentry --version
taxsentry --help
```

### 3. Configure and validate

```powershell
taxsentry setup
taxsentry doctor
taxsentry
```

The first command that enters the Python core creates the managed runtime automatically. Later package versions reinstall the bundled wheel when the runtime version sentinel changes.

## Installation options

### npm — recommended

```powershell
npm install -g taxsentry
taxsentry setup
```

The npm launcher handles `--help` and `--version` directly. All other arguments are forwarded to `python -m taxsentry` in the isolated managed runtime.

### uv tool — direct Python installation

```powershell
uv tool install git+https://github.com/thienan230427/TaxSentry.git
taxsentry setup
taxsentry doctor
```

### Source checkout — development

```powershell
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
uv sync --locked --extra dev
uv run taxsentry setup
```

If TaxSentry detects a v1 profile, it moves the old profile to a timestamped backup directory before creating the v2 profile. Existing data is not silently deleted.

To use the PostgreSQL and S3/MinIO APIs from the source environment, install the
optional dependencies declared by the repository:

```powershell
uv sync --extra dev --extra distributed
```

The Docker worker installs the same pinned clients directly. Deployment,
migration, and rollback details are in
[TaxSentry 3 development architecture and operations](docs/taxsentry-3.md).

## Interactive setup

Run:

```powershell
taxsentry setup
```

The bilingual wizard offers two paths:

- **Quick Setup** configures the provider and model, disables Gmail and Telegram, and opens chat quickly.
- **Full Setup** lets you select a profile and configure every enabled service.

### Profiles

| Profile | Terminal AI | Gmail workflow | Telegram gateway | Recommended use |
| --- | :---: | :---: | :---: | --- |
| **Chat Only** | Yes | No | No | Conversations and local document generation |
| **Email Agent** | Yes | Yes | No | Gmail attachment processing and email reports |
| **Full Agent** | Yes | Yes | Yes | Gmail automation plus remote Telegram access |

```mermaid
flowchart TD
    Start["Choose setup path"] --> Quick{"Need Gmail or Telegram?"}
    Quick -->|"No"| QuickSetup["Quick Setup"]
    Quick -->|"Yes"| FullSetup["Full Setup"]
    FullSetup --> Profile{"Choose profile"}
    Profile --> Chat["Chat Only"]
    Profile --> Email["Email Agent"]
    Profile --> Full["Full Agent"]
```

### Setup sequence

1. Choose Vietnamese or English.
2. Select Quick Setup or Full Setup.
3. Select Codex / ChatGPT or LM Studio.
4. Authenticate and choose a discovered or custom model.
5. For Gmail, enter the connected account, polling interval, and 16-character App Password.
6. For Telegram, enter one or more chat IDs and a bot token.
7. Review the summary and authenticate the selected services.
8. Save non-secret configuration only after validation succeeds.

The wizard keeps the existing configuration unchanged when it is cancelled or validation fails. Gmail App Passwords and Telegram bot tokens are stored in the operating-system keyring, not in `config.json`.

### Gmail preparation

1. Enable Google 2-Step Verification.
2. Create a 16-character [Google App Password](https://myaccount.google.com/apppasswords).
3. Run `taxsentry setup` and enter the Gmail address and App Password.
4. Run `taxsentry doctor` to verify the keyring entry, worker marker, OCR runtime, and provider.

The same Gmail account is used for IMAP reading, SMTP delivery, and receiving generated reports.

### Telegram preparation

1. Create a bot with [BotFather](https://t.me/BotFather).
2. Obtain the numeric chat IDs that may use the bot.
3. Enter the IDs and bot token during Full Setup.
4. TaxSentry verifies the token before replacing the saved secret.

## Command reference

### CLI commands

| Command | Purpose |
| --- | --- |
| `taxsentry` | Run setup on first use, then open the Financial Sentinel TUI. |
| `taxsentry --help` | Show public commands. |
| `taxsentry --version` | Print the installed version. |
| `taxsentry setup` | Create or update the local profile. |
| `taxsentry status` | Show provider, Gmail, Telegram, LibreOffice, and configuration status. |
| `taxsentry doctor` | Check the provider and enabled integrations. |
| `taxsentry doctor --fix` | Create required directories and attempt to install missing Tesseract components. |
| `taxsentry update` | Update through the stable channel for the detected installation type. |
| `taxsentry update --main` | Explicitly update the Python core from GitHub `main`. |
| `taxsentry migrate-v3 [--sqlite PATH] [--backup-dir DIR] [--company-id ID]` | Back up a v2 SQLite store, ensure the PostgreSQL schema, import supported data/object references, and write a JSON migration report. |

### Terminal commands

Type `/` to show command completion. Use the arrow keys to select a command, `Tab` to complete it, and `Esc` to close the suggestions.

| Command | Purpose |
| --- | --- |
| `/help` | Show commands and keyboard shortcuts. |
| `/status` | Show provider, Gmail, Telegram, and Office status. |
| `/gmail` | List recent Gmail results using the default query. |
| `/gmail search <query>` | Search up to 20 messages with Gmail search syntax. |
| `/gmail read <uid>` | Read one message, including body and attachment names. |
| `/gmail process <uid\|all>` | Confirm processing for selected search results. |
| `/create [docx\|xlsx\|pptx\|pdf] <request>` | Generate one requested file or let TaxSentry select an advisory bundle. Add `--template <path>` for a compatible Office template. |
| `/profile show` | Show the controlled company profile used by advisory reports. |
| `/profile set <field> <value>` | Update an approved company-profile field. |
| `/knowledge status` | Show legal-source verification and freshness. |
| `/knowledge refresh` | Refresh the allowlisted official-source registry. |
| `/skills list\|install\|github\|draft\|approve\|rollback\|disable ...` | Inspect or govern local, pinned-GitHub, and agent-drafted skills; installs remain drafts until approved. |
| `/cancel <job-prefix>` | Request cancellation of an active job. |
| `/jobs` | Show recent job IDs, states, subjects, and retry counts. |
| `/report` | Show the executive summary from the latest report. |
| `/retry [job-prefix]` | Requeue a failed or review-pending job. |
| `/approve [job-prefix]` | Approve and deliver the already-rendered draft without re-running analysis. |
| `/new` | Start a new conversation session. |
| `/resume <session-id>` | Resume a saved session from the selected company. |
| `/sessions <query>` | Search saved sessions and messages within the selected company. |
| `/forget <memory-id>` | Delete one curated-memory item in the selected company and retain a content-free audit tombstone. |
| `/agent reload` | Rebuild the current session's identity/memory/skill prompt snapshot and reset its provider thread. |
| `/exit` | Stop background services and exit safely. |

Examples:

```text
Which unread emails arrived today?
/gmail search from:invoice@example.com has:attachment newer_than:30d
/gmail read 1842
/gmail process 1842
/create pdf Summarize the current month's Gmail reports
/create xlsx Build a management dashboard from "D:\Reports\June.xlsx"
/create pptx Create a board presentation --template "D:\Templates\Board.pptx"
```

### Telegram commands

| Command | Purpose |
| --- | --- |
| `/status`, `/jobs` | List recent jobs and their states. |
| `/report` | Send the latest generated PDF. |
| `/gmail search <query>` | Search Gmail and retain results for confirmation. |
| `/gmail process <uid\|all>` | Process confirmed Gmail results. |
| `/create [docx\|xlsx\|pptx\|pdf] <request>` | Generate a requested file or an automatically selected advisory bundle. |
| `/profile show\|set ...` | View or update the controlled company profile. |
| `/knowledge status\|refresh` | Inspect or refresh official legal sources. |
| `/retry <job-prefix>` | Requeue a failed or review-pending job. |
| `/approve <job-prefix>` | Approve a review-pending job. |
| `/cancel <job-prefix>` | Cancel an active workflow job. |
| `/new`, `/resume <session-id>` | Start a new shared session or resume one owned by the selected company. |
| `/sessions <query>` | Search that company's saved sessions. |
| `/forget <memory-id>` | Remove one curated-memory item in the selected company. |
| `/agent reload` | Rebuild the current prompt snapshot and reset the provider thread. |
| Plain text | Chat with the shared TaxSentry assistant. |

## Supported documents

| Extension | Validation and extraction |
| --- | --- |
| `.docx` | Open XML validation plus structural paragraphs, headings/sections, tables, headers/footers, notes/comments, tracked-change text, and embedded-image OCR. |
| `.xlsx`, `.xlsm` | Open XML validation plus all-sheet inventory, streaming row units, formulas/cached values, merged cells, names, chart sources, and external-link metadata. VBA is never executed. |
| `.pptx` | Open XML validation plus slides, shapes, tables, chart series, speaker notes, comments, theme/master metadata, and embedded-image OCR. |
| `.pdf` | PDF signature validation, per-page direct extraction, and page-selective OCR when text is sparse. |
| `.png` | PNG signature validation and Tesseract OCR. |
| `.jpg`, `.jpeg` | JPEG signature validation and Tesseract OCR. |
| `.doc`, `.xls`, `.ppt` | Compound-file signature validation, then headless LibreOffice conversion when the sandbox flag is enabled. |

Macro-enabled `.docm` and `.pptm` files are not accepted. `.xlsm` is accepted as workbook data, but TaxSentry does not execute macros or open external links. Email and document content is treated as untrusted data: TaxSentry does not execute scripts, links, or instructions embedded in source files.

The configured single-document and aggregate case limit is **500 MB**. Open XML expansion is capped at **4 GiB**, 100,000 entries, and a 1,000:1 compression ratio. A synthetic 498 MiB case with 100 Excel sheets/1,000,000 rows, 1,000 PDF pages, 500 slides, and a long Word document completed with 7,609/7,609 units covered; see the [recorded acceptance result](docs/benchmarks/acceptance-2026-07-27.md). Every inventoried unit must be processed or appear explicitly as failed/skipped in the coverage report.

## Gmail processing lifecycle

```mermaid
stateDiagram-v2
    [*] --> queued: new or confirmed attachment
    queued --> fetching
    fetching --> extracting
    extracting --> analyzing
    analyzing --> rendering
    rendering --> delivering
    delivering --> completed
    fetching --> queued: retryable failure
    extracting --> queued: retryable failure
    analyzing --> queued: retryable failure
    rendering --> queued: retryable failure
    delivering --> delivering: retry failed channel only
    queued --> cancelled: user cancellation
    fetching --> cancelled: user cancellation
    extracting --> cancelled: user cancellation
    analyzing --> cancelled: user cancellation
    rendering --> cancelled: user cancellation
    delivering --> cancelled: user cancellation
    queued --> failed: retry limit reached
    fetching --> failed: retry limit reached
    extracting --> failed: retry limit reached
    analyzing --> failed: retry limit reached
    rendering --> failed: retry limit reached
    delivering --> failed: retry limit reached
    failed --> queued: /retry
    needs_review --> queued: /approve or /retry
    completed --> [*]
```

For every supported attachment, TaxSentry:

1. Creates a stable job identifier from the Gmail message identity and attachment SHA-256.
2. Validates the extension, MIME type, file signature, archive structure, and configured size limit.
3. Saves the validated attachment under `~/.taxsentry/downloads/<job-id>/`.
4. Extracts structured content or OCR text.
5. Builds deterministic metrics and retrieves relevant, freshness-scored knowledge.
6. Requests an Advisory Schema v2 analysis and removes unsupported benchmarks or numbers.
7. Renders the exact profile-selected bundle and records its main legacy `pdf_path` plus every output path in SQLite.
8. Holds material, low-confidence, high-tax-risk, or stale-source reports for approval.
9. Delivers the saved draft after approval without re-running extraction or analysis.
10. Records each successful file/channel so retries do not duplicate completed deliveries.
11. Applies the final Gmail workflow label.

## Architecture

```mermaid
flowchart TB
    CLI["npm TypeScript launcher"] --> Runtime["Managed Python 3.11-3.13 virtual environment"]
    Runtime --> Entry["python -m taxsentry"]
    Entry --> Setup["Transactional setup wizard"]
    Entry --> Cockpit["Textual terminal cockpit"]
    Cockpit --> Chat["Shared ChatService"]
    Cockpit --> Worker["Gmail polling worker"]
    Cockpit --> Telegram["Telegram bot gateway"]
    Chat --> Prompt["PromptAssembler"]
    Prompt --> Identity["SOUL · USER · COMPANY · MEMORY · AGENTS"]
    Chat --> Provider["Codex App Server or LM Studio"]
    Worker --> Workflow["TaxSentryWorkflow"]
    Workflow --> Documents["DocumentService and coverage"]
    Workflow --> Reporting["Structured analysis and ArtifactSpec"]
    Workflow --> Database[("SQLite compatibility workflow state")]
    Documents --> LocalObjects[("Local object store")]
    Documents --> Coordinator["Configured document coordinator"]
    Coordinator --> Queue[("PostgreSQL + pgvector job plane")]
    Queue --> LeaseWorker["Lease-based Docker workers"]
    LeaseWorker --> Documents
    LeaseWorker --> Objects[("MinIO or S3-compatible objects")]
    Cockpit --> Artifacts["ArtifactService"]
    Telegram --> Chat
    Telegram --> Workflow
    Telegram --> Artifacts
```

### Runtime boundaries

- **TypeScript launcher:** discovers `uv`, creates the managed virtual environment, installs the bundled wheel, forwards signals, and forces UTF-8 for the Python child process.
- **Python core:** owns setup, providers, prompt assembly, memory, TUI, Gmail, Telegram, Document Intelligence, workflow state, report rendering, artifact generation, jurisdiction guards, skills, and updates.
- **SQLite compatibility store:** remains the local store for jobs, state transitions, approvals, reports, attachments, deliveries, and events. It also stores sessions/messages/memory when distributed mode is disabled.
- **Distributed document plane:** when enabled, the shared `DocumentService` facade used by Gmail workflows and artifact generation submits document jobs to PostgreSQL lease/checkpoint workers and exchanges results through MinIO/S3. PostgreSQL also becomes the operational session/message/memory store; legacy workflow state remains in SQLite for compatibility.
- **OS keyring:** stores Gmail App Passwords and Telegram bot tokens.
- **Local profile:** stores non-secret configuration and generated workflow data under `~/.taxsentry` unless overridden.

The included [`deploy/compose.yml`](deploy/compose.yml) is for local development.
It deliberately uses PostgreSQL without TLS and MinIO over HTTP. Do not expose
it unchanged; the [TaxSentry 3 operations guide](docs/taxsentry-3.md) defines the
TLS, credential, encryption, network, backup, migration, and rollback
requirements for multi-host deployment.

## Configuration and local data

Default profile layout:

```text
~/.taxsentry/
├── config.json                 # non-secret configuration
├── taxsentry.db                # local workflow state and default agent state
├── SOUL.md                     # agent identity and communication style
├── USER.md                     # confirmed user preferences
├── MEMORY.md                   # global curated-memory snapshot
├── companies/<company-id>/
│   ├── COMPANY.md              # scoped company profile
│   └── MEMORY.md               # scoped curated-memory snapshot
├── skills/                     # drafts, approved versions, and registry state
├── documents/                  # document manifests and unit JSONL
├── objects/                    # default local content-addressed object store
├── sessions.jsonl              # reserved session path
├── logs/                       # runtime logs directory
├── run/                        # worker lock and runtime files
├── downloads/<job-id>/         # validated inputs and generated workflow reports
├── outputs/                    # documents created with /create
├── runtime/
│   ├── installed-version       # npm runtime version sentinel
│   └── venv/                   # isolated Python environment
└── codex/                      # isolated Codex App Server home
```

### Important settings

| Key | Default | Purpose |
| --- | --- | --- |
| `ui.language` | `vi` | Interface language: `vi` or `en`. |
| `provider.kind` | `lmstudio` | `lmstudio` or `codex`. |
| `provider.model` | empty | Selected model; empty lets the provider decide. |
| `gmail.enabled` | `true` | Enable Gmail search and the background worker. |
| `gmail.account` | empty | Gmail account used for IMAP and SMTP. |
| `gmail.process_after_uids` | `{}` | Per-mailbox automatic-processing markers. |
| `director.telegram_chat_ids` | `[]` | Authorized Telegram chats and report destinations. |
| `telegram.enabled` | `false` | Enable the Telegram gateway and delivery. |
| `worker.poll_seconds` | `30` | Delay after each Gmail polling cycle. |
| `worker.max_retries` | `3` | Retry limit for workflow and delivery failures. |
| `worker.max_attachment_mb` | `500` | Per-file input limit. |
| `documents.max_case_mb` | `500` | Aggregate `DocumentService.ingest_case` input limit. |
| `documents.excel_rows_per_unit` | `250` | Default structural workbook row-chunk size. |
| `memory.retention_days` | `90` | Expiry for unpinned messages and curated memory. |
| `memory.soft_context_ratio` | `0.55` | Context-compression soft threshold. |
| `memory.hard_context_ratio` | `0.80` | Context-compression hard threshold. |
| `data_plane.postgres_dsn` | empty | Optional PostgreSQL data-plane DSN. |
| `data_plane.object_store.kind` | `local` | `local` by default; distributed workers use S3/MinIO environment settings. |
| `ocr.languages` | `vie`, `eng` | Tesseract language packs. |
| `ocr.minimum_confidence` | `70` | Extraction threshold used for report warnings. |
| `report.minimum_confidence` | `0.70` | Analysis threshold used for report warnings. |
| `artifacts.output_dir` | `~/.taxsentry/outputs` | Generated document directory. |
| `advisor.company.materiality_ratio` | `0.05` | Hold recommendations whose estimated impact reaches this share of period revenue. |
| `advisor.knowledge.refresh_days` | `7` | Automatic official-source refresh cadence. |
| `advisor.knowledge.legal_stale_days` | `30` | Maximum age before legal conclusions require review. |
| `advisor.knowledge.benchmark_max_age_months` | `24` | Maximum accepted benchmark age. |

### Environment overrides

| Variable | Effect |
| --- | --- |
| `TAXSENTRY_HOME` | Move the complete TaxSentry profile. |
| `TAXSENTRY_CONFIG_FILE` | Override the JSON configuration path. |
| `TAXSENTRY_MEMORY_DB` | Override the local SQLite compatibility database path. |
| `TAXSENTRY_AGENTS_FILE` | Override the repository/project `AGENTS.md` path used by prompt assembly. |
| `TAXSENTRY_POSTGRES_DSN` | Give a distributed worker a complete PostgreSQL DSN. |
| `TAXSENTRY_JOB_HANDLER` | Select the worker handler as `module:function`; document workers use `taxsentry.data_plane.document_worker:handle_document_job`. |
| `TAXSENTRY_S3_ENDPOINT`, `TAXSENTRY_S3_BUCKET` | Configure the S3-compatible object endpoint and bucket. |
| `TAXSENTRY_S3_ACCESS_KEY`, `TAXSENTRY_S3_SECRET_KEY` | Configure object-store service credentials. |
| `TAXSENTRY_S3_ALLOW_INSECURE` | Explicitly permit HTTP object storage for local development only. |
| `TAXSENTRY_S3_ENCRYPTION` | Request a supported S3 server-side encryption mode. |
| `TAXSENTRY_UV` | Point the npm launcher to a specific `uv` executable. |
| `CODEX_CLI_PATH` | Point TaxSentry to a specific Codex executable. |

## Security and reliability

- Secrets are stored in the operating-system keyring and excluded from persisted JSON.
- Incoming attachments must match the allowed extension, MIME type, and binary signature.
- Open XML files must contain their required package members and stay within expansion, entry-count, compression-ratio, and traversal limits.
- File names are reduced to their base name before saving, preventing attachment path traversal.
- Gmail and document text is placed in prompts as untrusted source data, with explicit instructions not to follow embedded commands.
- Macros and external Office links are inventoried where relevant but never executed or opened.
- Curated memory rejects untrusted sources and secret-like content and is isolated by company.
- Job identity includes the Gmail message identity and attachment SHA-256 to avoid duplicate processing.
- Gmail delivery uses a stable message ID and checks Sent mail before sending again.
- Successful delivery channels are recorded independently for safe retries.
- Provider analysis, extraction, Gmail access, and delivery have configurable timeouts.
- Telegram commands and data are restricted to configured chat IDs.
- Updates refuse to reset, stash, or overwrite a dirty Git working tree.

Never commit App Passwords, bot tokens, OAuth data, `.env` files, databases, downloaded attachments, generated reports, or local runtime directories.

## Updating

```powershell
taxsentry update
taxsentry update --main
```

| Installation | Stable update | `--main` behavior |
| --- | --- | --- |
| Git clone | Fast-forward the configured upstream, then run `uv sync --locked` | Requires the checked-out branch to be `main`; fast-forwards `origin/main`. |
| Global npm | Install a newer `taxsentry@latest` only when the registry version is greater | Reinstall the managed Python core from GitHub `main`. |
| uv tool | Run `uv tool upgrade taxsentry-agent` | Force-install the Python package from GitHub `main`. |

Restart the TUI after an update. Git-based updates require a clean working tree and never switch branches automatically.

## Troubleshooting

Start with:

```powershell
taxsentry status
taxsentry doctor
taxsentry doctor --fix
```

| Symptom | Cause | Resolution |
| --- | --- | --- |
| `uv` not found | The npm launcher cannot create its Python runtime. | Install `uv`, reopen the terminal, or set `TAXSENTRY_UV`. |
| No compatible Python | `uv` cannot find Python `>=3.11,<3.14`. | Install Python 3.11, 3.12, or 3.13 and rerun TaxSentry. |
| Gmail rejects the password | A normal password was used, the App Password is invalid, or 2-Step Verification is disabled. | Enable 2-Step Verification, create a new 16-character App Password, and rerun setup. |
| Gmail does not auto-process old mail | Automatic processing intentionally begins after setup markers. | Search history with `/gmail search`, inspect it, then confirm with `/gmail process`. |
| OCR language is missing | Tesseract or the `vie`/`eng` language data is unavailable. | Install the required language packs or run `taxsentry doctor --fix`. |
| Legacy Office file fails | LibreOffice is missing or conversion failed. | Install LibreOffice and confirm `soffice` is in `PATH`. |
| LM Studio check fails | The server is stopped, the URL is wrong, or no model is loaded. | Start LM Studio's local server, verify the `/v1` URL, and rerun setup. |
| Codex login cannot open a browser | Browser launch is unavailable. | Select device-code authentication in setup. |
| Telegram ignores a chat | Its numeric ID is not authorized. | Add the chat ID through `taxsentry setup`. |
| A job repeatedly fails | Input validation, provider, extraction, or delivery is failing. | Use `/jobs`, inspect the latest error, correct the dependency or credentials, then use `/retry`. |
| Git update refuses to run | The checkout is dirty or has no upstream. | Commit or stash changes yourself and configure an upstream. |
| Windows pytest temp failure | The default temporary-directory ACL blocks pytest. | Use a workspace-local `--basetemp` as shown below. |

## Development

### Python checks

```powershell
uv sync --locked --extra dev
uv lock --check
uv run ruff check src tests
uv run pytest -q
uv build
```

Windows fallback for restricted temporary folders:

```powershell
$env:TAXSENTRY_HOME='D:\TaxSentry\tmp-test-home'
$env:UV_CACHE_DIR='D:\TaxSentry\.uv-cache'
uv run pytest -q --basetemp=D:\TaxSentry\tmp-pytest -p no:cacheprovider
```

### npm launcher checks

```powershell
cd npm
npm ci
npm run typecheck
npm test
npm pack --dry-run --json
npm run smoke
```

The smoke test builds the Python wheel, packs the npm artifact, verifies that exactly one matching wheel is bundled, installs the tarball into an isolated prefix, creates the managed runtime, and exercises the installed launcher.

### Continuous integration

GitHub Actions validates:

- Python 3.11, 3.12, and 3.13 on Ubuntu.
- Python 3.12 on Windows and macOS.
- Ruff, pytest, lockfile consistency, and Python package builds.
- Node.js 24 launcher type-checks, tests, npm package contents, and smoke installation on Windows, macOS, and Ubuntu.

### Release checklist

Keep all version locations synchronized:

- `npm/package.json`
- `npm/package-lock.json`
- `pyproject.toml`
- `src/taxsentry/__init__.py`
- `uv.lock`

Then run the complete validation and inspect the actual npm package:

```powershell
cd D:\TaxSentry
uv lock --check
uv run ruff check src tests
uv run pytest -q

cd npm
npm run typecheck
npm test
npm run smoke
npm publish --dry-run
```

## Project structure

```text
TaxSentry/
├── .github/workflows/           # cross-platform CI
├── deploy/                      # local PostgreSQL/MinIO/worker development topology
├── docs/
│   └── taxsentry-3.md           # v3 architecture, deployment, migration, and rollback
├── npm/
│   ├── src/                     # TypeScript launcher and runtime bootstrap
│   ├── scripts/                 # prepack and smoke-install validation
│   ├── tests/                   # Node.js launcher tests
│   └── dist/vendor/             # bundled Python wheel
├── src/taxsentry/
│   ├── bot/                     # Telegram command gateway
│   ├── core/                    # financial XLSX parser and PDF generator
│   ├── data_plane/              # PostgreSQL leases, object stores, worker, and migration
│   ├── knowledge_base/          # identity defaults and verified Vietnam knowledge content
│   ├── artifacts.py             # DOCX, XLSX, PPTX, and PDF generation
│   ├── cockpit.py               # terminal interface
│   ├── config.py                # profile paths and defaults
│   ├── documents.py             # structural ingestion, manifests, evidence, and coverage
│   ├── extraction.py            # Office, PDF, and OCR extraction
│   ├── gmail.py                 # IMAP, SMTP, search, labels, and validation
│   ├── jurisdictions.py         # verified-pack guard and hybrid retrieval
│   ├── memory.py                # scoped curated memory and session services
│   ├── prompt.py                # identity and prompt snapshot assembly
│   ├── providers.py             # LM Studio and Codex App Server
│   ├── skills.py                # governed draft, approval, rollback, and sandbox APIs
│   ├── setup_wizard.py          # bilingual transactional setup
│   ├── store.py                 # SQLite workflow state plus PostgreSQL-backed agent-state adapter
│   ├── updater.py               # safe update channels
│   └── workflow.py              # document processing and delivery
├── tests/                       # Python unit and regression tests
├── stress_tests/                # representative financial workbooks
├── pyproject.toml               # Python package metadata
└── uv.lock                      # reproducible dependency lock
```

## Production checklist

- [ ] Read the [TaxSentry 3 deployment, migration, and rollback guide](docs/taxsentry-3.md); do not use the local Compose security settings on a network.
- [ ] Run `taxsentry doctor` on the target machine.
- [ ] Confirm the selected provider and model.
- [ ] Verify Gmail IMAP and SMTP with the production App Password.
- [ ] Confirm the automatic-processing marker was captured after setup.
- [ ] Confirm Telegram bot ownership and every authorized chat ID.
- [ ] Verify Tesseract `vie` and `eng` language packs when OCR is required.
- [ ] Verify LibreOffice when legacy Office formats are required.
- [ ] Process one representative document end to end.
- [ ] Compare the generated report with the original source evidence.
- [ ] Test a delivery failure and retry without duplicating the successful channel.
- [ ] Back up `~/.taxsentry` according to the organization's retention policy.
- [ ] For distributed deployment, verify PostgreSQL TLS/certificates, HTTPS object storage, scoped service credentials, encrypted volumes/backups, restore, and worker egress controls.
- [ ] Preserve the SQLite source and hashed migration export until rollback and reconciliation are signed off.

## License

TaxSentry is released under the [MIT License](LICENSE).

---

<div align="center">

**TaxSentry — evidence first, automation with human accountability.**

</div>
