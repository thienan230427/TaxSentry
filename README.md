# TaxSentry 2.0

TaxSentry is a Python-first AI agent for Vietnamese finance and tax-reporting workflows. It receives reports from Gmail, validates their origin and attachments, extracts data from spreadsheets, PDFs, and scanned images, generates structured analysis, renders a PDF report, and delivers the result through Gmail and Telegram.

> [!IMPORTANT]
> TaxSentry provides analysis, supporting evidence, confidence scores, and recommendations. It does not file taxes or make financial, legal, or operational decisions. A qualified person remains responsible for reviewing every material conclusion.

## Highlights

- Receives report attachments through the Gmail API.
- Processes messages only from addresses listed in `gmail.trusted_senders`.
- Supports XLSX, PDF, PNG, JPG, and JPEG files.
- Validates file extensions, MIME types, magic bytes, size limits, and SHA-256 hashes.
- Extracts spreadsheet data with a shared financial parser and uses Tesseract for scanned images and PDFs.
- Supports LM Studio and the official Codex App Server as AI providers.
- Normalizes model output into a fixed JSON report schema.
- Routes low-confidence extraction or analysis to human review.
- Tracks job state, retries transient failures, and recovers interrupted work after a restart.
- Prevents duplicate Gmail processing and duplicate outbound email delivery.
- Generates PDF reports and delivers them through Gmail and Telegram.
- Includes an interactive terminal cockpit, Telegram gateway, and native background service integration.
- Stores sensitive credentials in the operating system keyring instead of `config.json`.
- Runs on Windows, macOS, and Linux.

## Processing workflow

```text
Gmail
  -> trusted-sender and attachment validation
  -> queued
  -> fetching
  -> extracting
  -> analyzing
  -> needs_review or rendering
  -> delivering
  -> completed or failed
```

Failures are retried with exponential backoff up to the configured limit. Jobs in `needs_review` must be approved with `/approve` before processing continues.

## Requirements

- Python 3.11, 3.12, or 3.13.
- Node.js 22 or later when installing from npm.
- [uv](https://docs.astral.sh/uv/) for direct Python installation and source development.
- Tesseract OCR with the `vie` and `eng` language packs for scanned documents.
- A Gmail OAuth Desktop App when Gmail integration is enabled.
- Either:
  - LM Studio running at `http://127.0.0.1:1234/v1`; or
  - an authenticated Codex CLI installation.
- A Telegram bot token when Telegram delivery or remote control is enabled.

## Installation

### npm installation

Recommended for end users:

```powershell
npm install -g taxsentry
taxsentry setup
taxsentry doctor
```

The npm launcher installs its bundled Python core into `~/.taxsentry/runtime/venv`. User configuration, the SQLite database, logs, secrets, and generated reports remain under `~/.taxsentry` when the npm package is upgraded or removed.

### uv tool installation

Install directly from GitHub:

```powershell
uv tool install git+https://github.com/thienan230427/TaxSentry.git
taxsentry setup
taxsentry doctor
```

### Development installation

```powershell
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
uv sync --locked --extra dev
uv run taxsentry setup
```

`taxsentry setup` creates a profile in `~/.taxsentry`. When it detects a v1 profile, it moves that profile to a timestamped backup directory instead of deleting it.

## Initial configuration

Run the interactive setup and connect the required services:

```powershell
taxsentry setup
taxsentry auth gmail
taxsentry auth telegram
taxsentry auth codex
taxsentry auth status
taxsentry doctor
```

- Gmail uses the `gmail.modify` OAuth scope. Its refresh token is stored in the OS keyring.
- The Telegram bot token is stored in the OS keyring and is never written to `config.json`.
- Codex authentication is handled by the official `codex app-server`; TaxSentry does not manage the Codex OAuth token.
- LM Studio uses an OpenAI-compatible local endpoint. Select the provider and model during setup.
- `taxsentry doctor --fix` creates missing runtime directories and can attempt to install Tesseract with the native package manager.

Important configuration keys:

| Key | Purpose |
| --- | --- |
| `gmail.account` | Gmail account that receives reports |
| `gmail.oauth_client_file` | Path to the Gmail OAuth `credentials.json` file |
| `gmail.trusted_senders` | Allowlist of authorized report senders |
| `director.email` | Recipient of generated PDF reports |
| `director.telegram_chat_ids` | Telegram chat IDs allowed to receive reports and issue commands |
| `provider.kind` | `lmstudio` or `codex` |
| `provider.model` | Model used for analysis |
| `worker.poll_seconds` | Gmail polling interval |
| `worker.max_retries` | Maximum processing attempts per job |
| `ocr.minimum_confidence` | Minimum OCR confidence; default: `70%` |
| `report.minimum_confidence` | Minimum report confidence; default: `70%` |

## Command-line reference

```text
taxsentry                       Open the terminal cockpit
taxsentry chat                  Open the terminal cockpit
taxsentry start                 Open the terminal cockpit
taxsentry setup                 Create or update the local profile
taxsentry status                Show the current configuration summary
taxsentry doctor [--fix]        Validate dependencies and integrations
taxsentry gateway               Run the Telegram gateway in the foreground
taxsentry worker run            Run the worker continuously
taxsentry worker run --once     Process one polling cycle and exit
taxsentry worker run --gateway  Run the worker and Telegram gateway together
taxsentry jobs                  List recent jobs
taxsentry report                Print the latest report as JSON
taxsentry report --send         Confirm and resend the latest report
taxsentry auth gmail            Authenticate Gmail
taxsentry auth telegram         Store the Telegram bot token
taxsentry auth codex            Authenticate through Codex App Server
taxsentry auth status           Show authentication and configuration status
taxsentry auth logout           Remove TaxSentry Gmail and Telegram secrets
taxsentry service <action>      Manage the native background service
taxsentry update                Update from the stable channel
taxsentry update --main         Update the Python core from GitHub main
```

Service actions are `install`, `start`, `stop`, `status`, `logs`, and `remove`.

## Terminal cockpit

The interactive cockpit accepts normal chat messages and the following slash commands:

| Command | Description |
| --- | --- |
| `/help` | List available commands |
| `/status`, `/auth` | Show configuration and authentication status |
| `/jobs` | List recent jobs |
| `/latest`, `/report` | Show the latest report summary |
| `/provider [codex\|lmstudio]` | Switch the active AI provider |
| `/retry [job]` | Requeue a failed or review-pending job |
| `/approve [job]` | Approve and requeue a review-pending job |
| `/clear` | Clear the current conversation context |
| `/exit` | Exit the cockpit |

`/quit` is a hidden alias for `/exit`.

## Telegram commands

Only chat IDs listed in `director.telegram_chat_ids` are authorized. The gateway supports:

- `/status` and `/jobs` — list recent job states.
- `/latest` — show the latest executive summary.
- `/report` — download the latest PDF report.
- `/retry <job>` — retry a failed or review-pending job.
- `/approve <job>` — approve a review-pending job.
- `/cancel <job>` — cancel a job and mark it as failed.

Authorized users may also send plain-text questions grounded in the latest report.

## Updating TaxSentry

```powershell
taxsentry update          # stable channel
taxsentry update --main   # latest code from GitHub main
```

The updater detects npm global installations, uv tools, and Git clones:

- A Git clone must have a clean working tree and is updated with a fast-forward-only pull followed by `uv sync --locked`.
- An npm installation checks the registry and refuses to downgrade the installed core.
- A uv tool uses `uv tool upgrade` for stable updates.
- `--main` is an explicit opt-in to the latest GitHub `main` code.

The updater never stashes, resets, or overwrites local Git changes. It preserves all data under `~/.taxsentry` and does not restart a running service automatically. After an update, restart the service when applicable:

```powershell
taxsentry service stop
taxsentry service start
```

## Background service

```powershell
taxsentry service install
taxsentry service start
taxsentry service status
taxsentry service logs
taxsentry service stop
taxsentry service remove
```

TaxSentry uses Task Scheduler on Windows, a LaunchAgent on macOS, and a user-level systemd service on Linux.

## Local data

TaxSentry stores runtime data in `~/.taxsentry` by default:

```text
config.json       Non-secret configuration
taxsentry.db      SQLite jobs, reports, deliveries, and events
logs/             Runtime logs
run/              Worker lock and runtime files
downloads/        Attachments and generated PDF reports
runtime/          Isolated Python runtime used by the npm launcher
```

Use `TAXSENTRY_HOME` to relocate the complete profile. `TAXSENTRY_CONFIG_FILE` and `TAXSENTRY_MEMORY_DB` can override the configuration and database paths independently.

## Security model

- Sender allowlisting is a mandatory trust boundary; messages from other senders are ignored and recorded as events.
- Attachments are validated before parsing.
- Secrets are stored in the OS keyring and excluded from the JSON configuration.
- Stable message and delivery identifiers prevent duplicate processing and outbound email delivery.
- Low-confidence results require explicit human approval.
- TaxSentry is designed as a single-organization internal tool, not a multi-tenant public service.
- AI-generated findings must be reviewed before they are used for financial decisions or tax filings.

Do not commit `.env` files, OAuth credentials, tokens, databases, downloaded attachments, or generated reports.

## Development and validation

```powershell
uv sync --locked --extra dev
uv lock --check
uv run ruff check src tests
uv run pytest -q
uv build

cd npm
npm ci
npm run typecheck
npm test
npm pack --dry-run
npm run smoke
```

The real-image OCR test is skipped automatically when Tesseract is unavailable. If the default temporary directory is restricted on Windows, use:

```powershell
uv run pytest -q --basetemp=D:\TaxSentry\tmp-pytest
```

GitHub Actions validates Python 3.11–3.13 and runs the npm launcher checks, package inspection, and smoke installation across Windows, macOS, and Ubuntu.

## Project structure

```text
TaxSentry/
├── src/taxsentry/       Python CLI, cockpit, workflow, integrations, and updater
├── tests/               Python unit and regression tests
├── npm/                 TypeScript launcher and bundled Python wheel
├── stress_tests/        Spreadsheet stress fixtures
├── .github/workflows/   Cross-platform CI
├── pyproject.toml        Python package metadata
└── uv.lock               Locked Python dependencies
```

## Production readiness

Before production use, validate Gmail OAuth, the selected AI provider, Telegram authorization, and Tesseract language packs on the target machine. Run at least one complete email-to-report delivery with representative data and review the generated analysis manually.

## License

TaxSentry is released under the [MIT License](LICENSE).
