# TaxSentry Cross-Platform Runtime Design

Date: 2026-06-19
Target OS: Windows, Linux, macOS

## Goal

Make TaxSentry run from a single codebase across Windows, Linux, and macOS without hardcoded machine paths, Windows-only bootstrapping, or shell-specific assumptions.

## Design Principles

1. No hardcoded absolute paths.
2. One source of truth for runtime paths and venv discovery.
3. OS-specific behavior isolated behind helper layers.
4. CLI launcher stays Node-based, analysis core stays Python-based.
5. Config and data stay user-editable; no platform values hardcoded in business logic.

## Runtime Architecture

### 1) Workspace layout
- Root package: `D:/TaxSentry`
- Python core: `taxsentry-core/`
- Node launcher: `src/`, `bin/`
- Runtime state:
  - Node side: `.taxsentry/`, `logs/`, `run/`
  - Python side: `.venv/`, `downloads/`, `scratch/`

### 2) Cross-platform bootstrap layer

Node launcher responsibilities:
- detect project-local Python venv
- construct `PYTHONPATH` with `path.delimiter`
- spawn Python modules with the correct cwd
- avoid assuming `;` or `\\` path separators

Python runtime responsibilities:
- detect whether running inside venv
- re-exec with `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on Unix
- discover project root from `pyproject.toml` / `requirements.txt`
- centralize path constants in `taxsentry.config.paths`

### 3) Platform capability adapters

TaxSentry should keep OS-sensitive logic behind adapters/helpers:
- `taxsentry.utils.runtime` for venv/project-root discovery
- launcher path helpers for Node-side spawn env
- PDF font fallback chain for Windows/macOS/Linux
- future service adapters for:
  - Windows Task Scheduler / PM2
  - systemd user service on Linux
  - launchd agent on macOS

## Implemented Foundation

### Already changed in repo
- Added `taxsentry.utils.runtime` as shared cross-platform bootstrap helper.
- Consolidated the interactive surface into:
  - `taxsentry/tui.py` as the CLI dispatcher
  - `taxsentry/ui/hermes_shell.py` as the agent cockpit
- Replaced duplicated Windows-first venv bootstrap logic in:
  - `taxsentry/__main__.py`
  - `taxsentry/bot/telegram_bot.py`
- Updated Node launcher to build `PYTHONPATH` using `path.delimiter` instead of Windows-only `;`.
- Removed hardcoded parser sample output/input paths in `excel_parser.py`; now uses config path constants.
- Updated PDF generator to resolve Unicode-capable fonts from Windows/macOS/Linux candidates instead of assuming only `C:/Windows/Fonts`.
- Removed hardcoded PDF demo output path; now uses `DOWNLOAD_DIR`.

## Remaining Work

### Phase 1 — Runtime normalization
- audit all shell commands for POSIX + Windows compatibility
- move any remaining path literals to config/constants
- add `.env.example` and OS-neutral onboarding docs

### Phase 2 — Dependency portability
- verify Python deps on Linux/macOS:
  - `reportlab`
  - `openpyxl`
  - `mysql-connector-python` or equivalent
  - Telegram deps
- verify Node package install on all target OSes
- document native prerequisites if any compiler/lib is required

### Phase 3 — Service management abstraction
Create a service adapter interface:
- `start_bot_service()`
- `stop_bot_service()`
- `service_status()`

Backends:
- Windows: current local child-process mode, optional Task Scheduler later
- Linux: systemd user unit or foreground supervisor mode
- macOS: launchd agent or foreground supervisor mode

### Phase 4 — Packaging
Recommended distribution strategy:
- Node CLI remains the primary entrypoint (`npx taxsentry` / global npm package)
- first-run installer creates Python venv and installs `taxsentry-core`
- optional Docker profile for headless Linux deployment

## Verification Matrix

Minimum smoke tests per OS:
1. `npm install`
2. onboarding / config bootstrap
3. status command
4. parser regression tests
5. PDF generation
6. Telegram bot dry start

## Suggested CI Matrix

GitHub Actions matrix:
- `windows-latest`
- `ubuntu-latest`
- `macos-latest`

Run:
- Node syntax checks
- Python import/compile checks
- parser regression tests

## Operational Recommendation

For local dev and demos:
- Windows remains the easiest default environment.

For production:
- Linux is the best target for always-on deployment.

For founder laptop usage:
- macOS should be treated as a first-class supported workstation, especially for setup/status/report-generation flows.
