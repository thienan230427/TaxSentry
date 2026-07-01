# TaxSentry 1.1.2

TaxSentry is a provider-first local AI agent for tax and finance workflows.
It combines a guided onboarding flow, a Hermes-style terminal cockpit, durable local memory, and service tooling for running the Telegram bot runtime in the background.

## What It Does

- Guides first-time setup with a friendly provider selection flow
- Runs a focused agent cockpit in the terminal
- Keeps memory, sessions, and artifacts local and inspectable
- Supports LM Studio, Codex OAuth, and OpenAI-compatible providers
- Exposes safe CLI commands for status, repair, reconfigure, and service management

## Installation

### From npm

```bash
npm install -g taxsentry@latest
```

### From this repository

```bash
npm install
npm run test
```

If you are running the repository locally, the CLI will use the Python core under `taxsentry-core/`.

## First Run

```bash
taxsentry setup
```

If you need to rebuild the local profile from scratch:

```bash
taxsentry reset-profile
```

If you only want to rerun onboarding while keeping the existing local profile:

```bash
taxsentry reconfigure
```

## CLI Reference

### Core commands

| Command | What it does |
| --- | --- |
| `taxsentry setup` | Install runtime dependencies and run the first-time onboarding wizard |
| `taxsentry start` | Open the interactive Hermes-style agent cockpit |
| `taxsentry status` | Show the current configuration and provider health |
| `taxsentry doctor` | Run a runtime health check |
| `taxsentry reconfigure` | Re-run onboarding without wiping existing secrets |
| `taxsentry reset-profile` | Reset the local profile and rerun onboarding from scratch |
| `taxsentry update` | Refresh runtime config, or self-update the installed package with `--self` |
| `taxsentry auth codex` | Link the current configuration to Codex OAuth |
| `taxsentry up` | Start the background agent process |
| `taxsentry stop` | Stop the background agent process |
| `taxsentry config` | Print the saved configuration |

### Update commands

```bash
taxsentry update
taxsentry update --self
taxsentry update --config-only
taxsentry update --package-spec taxsentry@latest
```

### Service commands

`taxsentry service` manages the Telegram bot service artifacts and OS registration.

| Command | What it does |
| --- | --- |
| `taxsentry service` | Show service status |
| `taxsentry service status` | Show service artifact and registration status |
| `taxsentry service install` | Generate the platform-specific service artifact |
| `taxsentry service apply` | Apply the generated service artifact to the host OS |
| `taxsentry service start` | Start the registered OS service |
| `taxsentry service stop` | Stop the registered OS service |
| `taxsentry service restart` | Restart the registered OS service |
| `taxsentry service remove` | Remove the OS registration for the service |
| `taxsentry service remove --purge-artifacts` | Remove OS registration and delete generated service files |
| `taxsentry service logs -n 100` | Show the latest service logs |

## Agent Slash Commands

Inside the agent cockpit, these slash commands are available:

- `/help`
- `/status`
- `/memory`
- `/remember <text>`
- `/mode <chat|analysis|execute|review|setup>`
- `/provider`
- `/audit`
- `/tools`
- `/trace`
- `/exit`

## Provider Options

### LM Studio

Recommended for local-first usage.

- Base URL: `http://localhost:1234/v1`
- Model: any model exposed by LM Studio
- API key: usually blank

### Codex OAuth

If Codex is already authenticated on the machine, TaxSentry can reuse that login.

### Custom endpoint

Use any OpenAI-compatible provider by setting:

- Base URL
- API key
- Model name

## Runtime Files

TaxSentry keeps its runtime state under your local TaxSentry home directory.

Typical files include:

- config JSON
- `.env`
- memory database
- session traces
- generated service artifacts

These files are designed to stay local and inspectable.

## Project Layout

- `bin/` - Node CLI entrypoint
- `src/` - Node orchestration, onboarding, service helpers, and config
- `taxsentry-core/src/taxsentry/` - Python runtime, agent kernel, memory, and TUI
- `tests/` - Node-level smoke and regression tests
- `taxsentry-core/tests/` - Python-level regression tests

## Verification

Common checks:

```bash
npm test
npm run lint
```

Python core checks:

```bash
cd taxsentry-core
python -m pytest tests
```

## Notes

- `taxsentry start` is the main interactive entrypoint.
- `taxsentry update --self` is the supported self-update path for published npm installs.
- The `service` command family is focused on the Telegram bot runtime and OS registration.

## License

MIT
