# TaxSentry

TaxSentry is a provider-first local AI agent for tax and finance workflows.
It gives you a guided setup wizard, a terminal agent cockpit, persistent local memory, session tracing, provider switching, and service tooling for background automation.

Current npm package: `taxsentry@1.1.4`

Repository: `https://github.com/thienan230427/TaxSentry`

## What TaxSentry Does

TaxSentry is designed to help you operate a local-first tax assistant from the terminal.

| Area | What it provides |
| --- | --- |
| Agent runtime | Central `AgentKernel`, router, planner, tool registry, session state |
| Chat cockpit | Interactive TUI with slash commands and provider-aware context |
| Memory | SQLite-backed local memory, recall, and `/remember` support |
| Providers | LM Studio, Codex OAuth, OpenAI-compatible endpoints |
| Workflow tools | Audit execution, report history, jobs, traces, dashboard |
| Service mode | Background Telegram bot service artifact management |
| Release safety | Node regression tests, Python tests, lint, cross-platform GitHub Actions |

## Quick Start

### 1. Install from npm

```bash
npm install -g taxsentry
```

Check that the CLI is available:

```bash
taxsentry --help
```

### 2. Run first-time setup

```bash
taxsentry setup
```

The setup wizard lets you choose:

- agent name, persona, and language
- model provider
- model name
- memory settings
- optional Telegram channel setup

### 3. Start the agent cockpit

```bash
taxsentry start
```

Inside the cockpit, try:

```text
/help
/status
/memory
/remember This project should verify provider health before release.
/mode analysis
/audit
/exit
```

### 4. Check system status

```bash
taxsentry status
taxsentry doctor
```

### 5. Open the dashboard

```bash
taxsentry dashboard
```

## Provider Setup

TaxSentry is provider-first. You choose the model backend during setup or later with `taxsentry reconfigure`.

### Option A: LM Studio

Use this when you want a local model server.

1. Open LM Studio.
2. Start the local OpenAI-compatible server.
3. Use this base URL:

```text
http://localhost:1234/v1
```

4. Run:

```bash
taxsentry setup
```

Recommended fields:

| Field | Value |
| --- | --- |
| Provider | LM Studio |
| Base URL | `http://localhost:1234/v1` |
| API key | blank or local placeholder |
| Model | any model exposed by LM Studio |

### Option B: Codex OAuth

Use this when Codex is already authenticated on the machine.

```bash
taxsentry auth codex
```

Then run:

```bash
taxsentry reconfigure
```

Choose:

```text
OpenAI Codex OAuth
```

### Option C: Custom OpenAI-Compatible Endpoint

Use this for OpenAI-compatible providers such as OpenRouter, local gateways, or custom model servers.

During setup, choose:

```text
Custom endpoint (OpenAI-compatible)
```

Provide:

| Field | Example |
| --- | --- |
| Base URL | `https://api.openai.com/v1` |
| API key | your provider key |
| Model | `gpt-4.1-mini`, `gpt-4.1`, or your gateway model |

## Main Commands

| Command | Purpose |
| --- | --- |
| `taxsentry setup` | Run first-time setup |
| `taxsentry setup --reset` | Reset and configure from scratch |
| `taxsentry start` | Open the interactive TUI |
| `taxsentry status` | Show current configuration and provider health |
| `taxsentry doctor` | Check runtime health |
| `taxsentry dashboard` | Open operational dashboard |
| `taxsentry jobs` | Show recent jobs |
| `taxsentry replay [sessionId]` | Replay a session trace |
| `taxsentry reconfigure` | Re-run onboarding without wiping secrets |
| `taxsentry reset-profile` | Fully reset local profile and onboarding state |
| `taxsentry auth codex` | Link config to Codex OAuth |
| `taxsentry update` | Refresh runtime config |
| `taxsentry update --self` | Self-update installed npm package |
| `taxsentry up` | Start background agent service mode |
| `taxsentry stop` | Stop background agent service mode |
| `taxsentry config` | Print saved configuration |

## Agent Slash Commands

Use these inside `taxsentry start`.

| Slash command | Purpose |
| --- | --- |
| `/help` | Show cockpit commands |
| `/status` | Show current agent status |
| `/memory` | Recall relevant local memory |
| `/remember <text>` | Save a fact or preference |
| `/mode chat` | Switch to chat mode |
| `/mode analysis` | Switch to analysis mode |
| `/mode execute` | Switch to execution mode |
| `/mode review` | Switch to review mode |
| `/provider` | Change provider |
| `/audit` | Run audit workflow |
| `/tools` | Show tool catalog |
| `/trace` | Show session trace |
| `/jobs` | Show recent jobs |
| `/replay [session_id]` | Replay a session |
| `/dashboard` | Open dashboard |
| `/exit` | Exit the cockpit |

## Background Service Commands

TaxSentry includes service helpers for background Telegram bot operation.

```bash
taxsentry service status
taxsentry service install
taxsentry service apply
taxsentry service start
taxsentry service stop
taxsentry service restart
taxsentry service logs -n 100
taxsentry service remove
taxsentry service remove --purge-artifacts
```

Typical flow:

```bash
taxsentry service install
taxsentry service apply
taxsentry service start
taxsentry service status
```

If you only want foreground/local use, you do not need service mode. Use:

```bash
taxsentry start
```

## Update Commands

Refresh runtime config:

```bash
taxsentry update
```

Refresh config only:

```bash
taxsentry update --config-only
```

Self-update from npm:

```bash
taxsentry update --self
```

Self-update with a specific package spec:

```bash
taxsentry update --self --package-spec taxsentry@1.1.4
```

## Local Development

### Requirements

- Node.js `>=24`
- Python `>=3.11`
- npm
- Git

### Clone and install

```bash
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
npm install
```

### Run the CLI from source

```bash
node bin/taxsentry.js --help
node bin/taxsentry.js setup
node bin/taxsentry.js start
```

Or use npm scripts:

```bash
npm run start
```

### Python core setup

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install Python dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r taxsentry-core/requirements.txt
python -m pip install pytest
```

Run Python tests:

```bash
cd taxsentry-core
PYTHONPATH=src python -m pytest tests
```

Windows PowerShell equivalent:

```powershell
cd taxsentry-core
$env:PYTHONPATH = "src"
python -m pytest tests
```

## Validation Before Shipping

Run these from the repository root:

```bash
npm test
npm run lint
```

Run Python tests:

```bash
cd taxsentry-core
PYTHONPATH=src python -m pytest tests
```

Run a package dry run:

```bash
npm pack --dry-run
```

Check GitHub Actions after pushing:

```bash
gh run list --repo thienan230427/TaxSentry --limit 5
```

## Project Layout

```text
TaxSentry/
  bin/
    taxsentry.js              # Node CLI entrypoint
  src/
    commands/                 # CLI command handlers
    utils/                    # Node helpers
    config.js                 # Node-side config/env handling
    onboarding.js             # Setup wizard
  taxsentry-core/
    src/taxsentry/
      agent/                  # Agent kernel, planner, state, tool registry
      runtime/                # Router, session, memory facade, policy, prompt
      database/               # SQLite stores
      ui/                     # TUI/dashboard
      core/                   # Parsing, audit, reports, automation
      bot/                    # Telegram bot runtime
      providers.py            # Provider client setup
      config.py               # Python-side config
    tests/                    # Python regression tests
  tests/                      # Node regression and package tests
  .github/workflows/          # Cross-platform CI
```

## Runtime Files

TaxSentry stores local runtime data under the local TaxSentry home directory.

Typical state includes:

- config JSON
- generated `.env`
- SQLite memory database
- session traces
- job logs
- generated service artifacts

These files are local runtime state and should not be committed.

## Environment Variables

The setup wizard writes these for the Python runtime:

```text
TAXSENTRY_AGENT_NAME=TaxSentry
TAXSENTRY_AGENT_PERSONA=warm, precise, and practical
TAXSENTRY_LANGUAGE=vi
TAXSENTRY_MEMORY_ENABLED=true
TAXSENTRY_PROVIDER_KIND=lmstudio
TAXSENTRY_PROVIDER_URL=http://localhost:1234/v1
TAXSENTRY_PROVIDER_MODEL=google/gemma-4-e4b
TAXSENTRY_AI_AUTH_MODE=lmstudio
TAXSENTRY_PROVIDER_API_KEY=
TAXSENTRY_LLM_PLANNER_ENABLED=false
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
ADMIN_CHAT_ID=
```

Use `taxsentry config` to inspect the saved configuration.

## Troubleshooting

### `taxsentry` command not found

Install globally:

```bash
npm install -g taxsentry
```

Or run from source:

```bash
node bin/taxsentry.js --help
```

### Provider is not reachable

Check status:

```bash
taxsentry status
taxsentry doctor
```

For LM Studio, make sure the local server is running at:

```text
http://localhost:1234/v1
```

### Codex OAuth is not available

Run:

```bash
taxsentry auth codex
```

Then:

```bash
taxsentry reconfigure
```

### Service mode does not start

Check generated artifacts and logs:

```bash
taxsentry service status
taxsentry service logs -n 100
```

Regenerate service files:

```bash
taxsentry service install
taxsentry service apply
```

### `npm publish` fails because the version already exists

npm versions are immutable. Bump first:

```bash
npm version patch
git push origin main --follow-tags
npm publish
```

### npm login required

Check current npm login:

```bash
npm whoami
```

If it fails:

```bash
npm login
```

## Publishing

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

- `prepublishOnly` runs `npm test` and `npm run lint`.
- `prepack` runs package smoke tests.
- Do not publish a version that already exists on npm.

## Current CI Status

The main branch is validated by GitHub Actions on:

- `windows-latest / python-3.11 / node-24`
- `ubuntu-latest / python-3.11 / node-24`
- `macos-latest / python-3.11 / node-24`

Expected gate before release:

```text
Cross-platform validation: success
```

## License

MIT
