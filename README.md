# TaxSentry

TaxSentry is a provider-first, local-first AI agent for tax and finance workflows.
It combines a guided setup wizard, a terminal cockpit, persistent local memory, session tracing, report replay, provider switching, and background service tooling for automation.

Current version: `1.1.7`

Repository: `https://github.com/thienan230427/TaxSentry`

## Overview

TaxSentry is built for teams that want a local assistant for accounting, tax review, and operational follow-up without giving up control of the runtime.

The project has two layers:

- a TypeScript CLI that handles onboarding, TUI launch, service management, and user-facing workflows
- a Python core that performs provider access, memory, session tracking, parsing, analysis, PDF generation, email delivery, Telegram delivery, and automation

## What TaxSentry Can Do

| Area | Capability |
| --- | --- |
| Setup | Guided first-run wizard, provider selection, memory settings, Telegram setup |
| Chat cockpit | Interactive terminal UI with slash commands and provider-aware context |
| Providers | LM Studio, Codex OAuth, and any OpenAI-compatible endpoint |
| Memory | Persistent SQLite-backed memory with remember, recall, and forget support |
| Sessions | Session log, event trace, replay bundle, and timeline storage |
| Jobs | Job lifecycle tracking, retry metadata, and failure status propagation |
| Finance parsing | Flexible Excel parsing, payroll extraction, canonical metric mapping |
| Analysis | AI audit engine that reads parsed data plus Vietnamese tax knowledge |
| Reports | Markdown report generation, PDF export, and report history |
| Delivery | SMTP email delivery and Telegram bot delivery |
| Automation | Inbox polling, attachment download, parse -> audit -> PDF -> send flow |
| Service mode | Platform-specific service artifact generation and OS service controls |
| Release safety | Node regression tests, Python tests, linting, and packaging smoke checks |

## Key Features

### 1. Provider-first setup

Choose the provider that matches your environment:

- LM Studio for local model serving
- Codex OAuth for the logged-in ChatGPT/Codex account
- OpenAI-compatible providers such as OpenRouter or custom gateways

The onboarding flow writes runtime config, `.env`, and local state files automatically.

### 2. Terminal cockpit

Launch the cockpit with `taxsentry start` to get:

- a focused chat surface
- slash commands for operational tasks
- live provider state and session context
- quick access to memory, jobs, reports, and replay data

### 3. Persistent memory

TaxSentry stores facts in SQLite and supports:

- saving preferences and project facts
- recalling relevant memory by keyword and accent-insensitive matching
- forgetting stored facts
- compact memory summaries in the TUI and copilot prompts

### 4. Session tracing and replay

The runtime records:

- session starts and ends
- user and assistant messages
- tool execution
- job events
- report provenance and trace metadata

That data powers:

- `taxsentry replay`
- the dashboard
- evidence previews
- report provenance in email and Telegram

### 5. Excel and finance analysis

The Python core can parse workbooks with:

- income statement-like sheets
- payroll sheets
- tax summary sheets
- assumptions sheets
- generic tabular sheets

It extracts canonical metrics such as:

- revenue
- gross profit
- total OPEX
- net income
- total income
- personal income tax
- social insurance
- net pay

### 6. AI audit generation

The audit engine:

- compacts parsed finance data
- loads the Vietnamese tax knowledge base
- sends a structured prompt to the selected provider
- writes the generated report to `audit_report.md`

### 7. PDF, email, and Telegram delivery

TaxSentry can:

- render Markdown reports to PDF
- email the report as an attachment
- send the report and evidence preview to Telegram
- preserve trace metadata on outbound artifacts

### 8. Automation loop

The automation workflow can:

- poll an inbox
- download allowed attachments
- parse Excel or PDF inputs
- run the audit engine
- generate PDF output
- send email and Telegram notifications
- mark emails as processed only after successful completion

### 9. Service mode

The service command set can generate and manage OS service artifacts for a Telegram bot runtime across supported platforms.

## CLI Commands

### Main commands

| Command | Description |
| --- | --- |
| `taxsentry setup` | Run the provider-first setup wizard |
| `taxsentry setup --reset` | Reconfigure from scratch |
| `taxsentry start` | Open the interactive terminal cockpit |
| `taxsentry status` | Show saved configuration and provider health |
| `taxsentry doctor` | Run a runtime health report |
| `taxsentry dashboard` | Open the read-only operational dashboard |
| `taxsentry jobs` | Show recent jobs |
| `taxsentry replay [sessionId]` | Replay a session trace |
| `taxsentry reconfigure` | Re-run onboarding without wiping secrets |
| `taxsentry reset-profile` | Reset local profile and onboarding state |
| `taxsentry auth codex` | Link the current config to Codex OAuth |
| `taxsentry update` | Refresh runtime config |
| `taxsentry update --self` | Self-update the installed npm package |
| `taxsentry update --config-only` | Refresh config without self-update |
| `taxsentry up` | Start the background agent in service mode |
| `taxsentry stop` | Stop the background agent |
| `taxsentry config` | Print the saved configuration |

### Service subcommands

| Command | Description |
| --- | --- |
| `taxsentry service` | Show service status |
| `taxsentry service status` | Show artifact and registration status |
| `taxsentry service install` | Generate platform-specific service artifacts |
| `taxsentry service apply` | Apply the service artifact to the host OS |
| `taxsentry service start` | Start the registered OS service |
| `taxsentry service stop` | Stop the registered OS service |
| `taxsentry service restart` | Restart the registered OS service |
| `taxsentry service remove` | Remove the service registration |
| `taxsentry service remove --purge-artifacts` | Remove registration and delete local artifacts |
| `taxsentry service logs -n 100` | Show recent service logs |

## Slash Commands in the Cockpit

Use these inside `taxsentry start`:

| Slash command | Description |
| --- | --- |
| `/help` | Show cockpit commands |
| `/status` | Show current agent status |
| `/memory` | Recall relevant local memory |
| `/remember <text>` | Save a fact or preference |
| `/mode chat` | Switch to chat mode |
| `/mode analysis` | Switch to analysis mode |
| `/mode execute` | Switch to execute mode |
| `/mode review` | Switch to review mode |
| `/mode setup` | Switch to setup mode |
| `/provider` | Change provider |
| `/audit` | Run the tax audit workflow |
| `/tools` | Show available tools |
| `/trace` | Show the current trace bundle |
| `/jobs` | Show recent jobs |
| `/replay [session_id]` | Replay a session |
| `/dashboard` | Open the dashboard |
| `/exit` | Exit the cockpit |

## Runtime Architecture

### Node layer

The TypeScript entrypoint is `bin/taxsentry.ts`.

It wires together:

- command registration
- onboarding
- config display
- Codex OAuth linking
- update and self-update flow
- service artifact management
- foreground and background runtime launchers

### Python core

The Python runtime lives under `taxsentry-core/src/taxsentry`.

Main modules include:

- `agent/` for kernel, planner, request/response models, and tool registry
- `runtime/` for routing, policy, composition, session tracking, and service facade
- `database/` for SQLite-backed memory, session, artifact, and report storage
- `core/` for Excel parsing, PDF generation, email, Telegram, automation, and audit engine
- `ui/` for the TUI and dashboard
- `bot/` for the Telegram bot runtime

## Setup

### Requirements

- Node.js `>=24`
- Python `>=3.10`
- npm
- Git

### Install from source

```bash
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
npm install
```

### Install Python dependencies

```bash
cd taxsentry-core
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pytest
```

### Run the setup wizard

```bash
taxsentry setup
```

### Start the cockpit

```bash
taxsentry start
```

## Configuration

TaxSentry stores local runtime data under the configured TaxSentry home directory.

Default paths are derived from `TAXSENTRY_HOME` and related environment variables.

### Important environment variables

| Variable | Purpose |
| --- | --- |
| `TAXSENTRY_HOME` | Root directory for local state |
| `TAXSENTRY_CONFIG_FILE` | JSON config path |
| `TAXSENTRY_MEMORY_DB` | SQLite memory DB path |
| `TAXSENTRY_SESSION_FILE` | Session file path |
| `TAXSENTRY_AGENT_NAME` | Agent display name |
| `TAXSENTRY_AGENT_PERSONA` | Agent persona |
| `TAXSENTRY_LANGUAGE` | Default language |
| `TAXSENTRY_PROVIDER_KIND` | Provider kind |
| `TAXSENTRY_PROVIDER_URL` | OpenAI-compatible base URL |
| `TAXSENTRY_PROVIDER_MODEL` | Provider model name |
| `TAXSENTRY_AI_AUTH_MODE` | Auth mode |
| `TAXSENTRY_PROVIDER_API_KEY` | Provider API key |
| `TAXSENTRY_MEMORY_ENABLED` | Enable memory |
| `TAXSENTRY_LLM_PLANNER_ENABLED` | Enable LLM planner |
| `TELEGRAM_ENABLED` | Enable Telegram integration |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `ADMIN_CHAT_ID` | Telegram admin chat ID |

### Provider notes

- LM Studio uses the local OpenAI-compatible endpoint, usually `http://localhost:1234/v1`
- Codex OAuth reads the profile from `~/.codex/auth.json`
- Custom providers should expose an OpenAI-compatible API

## Automation Pipeline

1. Poll inbox for allowed senders
2. Download allowed Excel/PDF/image attachments
3. Build evidence context and trace metadata
4. Parse workbook or PDF
5. Store parsed data and report logs in SQLite
6. Run AI audit against parsed data and Vietnamese tax knowledge
7. Generate Markdown and PDF reports
8. Send email and Telegram notifications
9. Mark the email as processed only after success

## Local Data and Artifacts

TaxSentry creates local state such as:

- configuration JSON
- `.env`
- SQLite memory database
- session store
- report log database
- parsed JSON exports
- evidence context
- generated PDFs
- service artifacts

These are runtime files and should not be committed.

## Development

### Run the Python core directly

```bash
cd taxsentry-core
python -m taxsentry
python -m taxsentry.tui
python -m taxsentry.bot.telegram_bot
```

### Run tests

```bash
npm test
```

```bash
cd taxsentry-core
python -m pytest tests
```

On Windows, if pytest hits a temp-path permission issue, run:

```bash
python -m pytest --basetemp=D:\TaxSentry\tmp-pytest tests
```

### Lint

```bash
npm run lint
```

### Package smoke test

```bash
npm pack --dry-run
```

## Release

Before publishing:

```bash
npm test
npm run lint
npm pack --dry-run
```

Patch release:

```bash
npm version patch
git push origin main --follow-tags
npm publish
```

Minor release:

```bash
npm version minor
git push origin main --follow-tags
npm publish
```

Notes:

- `prepublishOnly` runs tests and lint
- `prepack` runs the packaging smoke test
- do not publish a version that already exists on npm

## Troubleshooting

### `taxsentry` command not found

Install globally:

```bash
npm install -g taxsentry
```

Or run from source:

```bash
node bin/taxsentry.ts --help
```

### Provider is unreachable

Check:

```bash
taxsentry status
taxsentry doctor
```

### Codex OAuth is not available

Run:

```bash
taxsentry auth codex
```

### Service mode does not start

Check status and logs:

```bash
taxsentry service status
taxsentry service logs -n 100
```

Regenerate artifacts:

```bash
taxsentry service install
taxsentry service apply
```

## Project Layout

```text
TaxSentry/
  bin/                     # Node CLI entrypoints
  src/                     # Node CLI commands and helpers
  taxsentry-core/
    src/taxsentry/
      agent/               # Kernel, planner, request/response, tool registry
      runtime/             # Routing, policy, sessions, service facade
      database/            # SQLite stores and artifact metadata
      core/                # Excel, PDF, email, Telegram, automation, audit
      ui/                  # TUI and dashboard
      bot/                 # Telegram bot runtime
    tests/                 # Python regression and architecture tests
  tests/                   # Node regression and packaging tests
  docs/                    # Design notes and work logs
```

## Current CI

Main branch validation is expected on:

- `windows-latest / python-3.11 / node-24`
- `ubuntu-latest / python-3.11 / node-24`
- `macos-latest / python-3.11 / node-24`

## License

MIT


