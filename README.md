# TaxSentry

TaxSentry is a provider-first local AI agent with a guided setup wizard, persistent memory, and a polished terminal UI.

It is designed to make the first run feel simple: choose a provider, confirm the model, and launch into a usable workflow without fighting a wall of flags.

## Highlights

- Provider-first onboarding with clear setup cards
- Persistent local memory for durable facts and recent sessions
- Cross-platform terminal UI for Windows, macOS, and Linux
- Flexible provider support:
  - LM Studio
  - OpenAI Codex OAuth
  - Any OpenAI-compatible endpoint
- Safe, inspectable runtime files stored under your local TaxSentry home directory

## Installation

### From npm

```bash
npm install -g taxsentry@latest
```

### From this repository

```bash
npm install
npm run start
```

If this is the first launch, TaxSentry will guide you through setup automatically.

## First-time setup

```bash
taxsentry setup
```

You can reset and reconfigure later if needed:

```bash
taxsentry setup --reset
```

## Command reference

| Command | Description |
| --- | --- |
| `taxsentry start` | Open the interactive TUI in the foreground |
| `taxsentry up` | Start the background agent, kept as a legacy/background mode |
| `taxsentry stop` | Stop the background agent |
| `taxsentry status` | Show the current configuration and provider health |
| `taxsentry doctor` | Run a runtime health check |
| `taxsentry update` | Refresh runtime config only |
| `taxsentry update --self` | Install `taxsentry@latest` from npm, then refresh runtime config |
| `taxsentry auth codex` | Link the current configuration to Codex OAuth |
| `taxsentry config` | Print the current saved configuration |
| `taxsentry banner` | Show the TaxSentry wordmark |

### Practical usage flow

```bash
taxsentry setup
# or, after installing from npm:
taxsentry start
```

If you publish a new version to npm and want existing installs to update themselves:

```bash
taxsentry update --self
```

If you only want to refresh local config without changing the installed package:

```bash
taxsentry update
```

## Provider options

### LM Studio

Recommended for local-first usage.

- Base URL: `http://localhost:1234/v1`
- Model: any model available in LM Studio
- API key: usually blank for local servers

### OpenAI Codex OAuth

If Codex is already authenticated on the machine, TaxSentry can reuse that login and talk to the OpenAI API through OAuth-backed credentials.

### Custom endpoint

Use any OpenAI-compatible provider by supplying:

- Base URL
- API key
- Model name

## Memory

TaxSentry stores durable facts and recent turns under `~/.taxsentry/memory/`.

The memory layer is intentionally simple and inspectable:

- recent facts are persisted
- recent turns are stored per session
- prompts include a compact memory context

## Project layout

- `bin/taxsentry.js` — CLI entrypoint and help text
- `src/` — Node orchestration, setup, launcher, and configuration logic
- `taxsentry-core/src/taxsentry/` — Python runtime, memory store, provider abstraction, and TUI

## Publishing notes

The package is prepared for npm publishing and includes smoke tests that verify the tarball contents and the absence of secret files.

For a release workflow, the typical order is:

1. Update the code and documentation
2. Run the test and lint checks
3. Publish to npm
4. Ask users to run `taxsentry update --self` to pull the latest release

## License

MIT
