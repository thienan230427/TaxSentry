# TaxSentry 1.1.2

TaxSentry is a provider-first local AI agent for tax and finance workflows.
It combines a guided setup flow, a Hermes-style terminal cockpit, durable local memory, and service tooling for background execution.

## Highlights

- Guided onboarding for first-time setup
- Interactive terminal cockpit for day-to-day agent work
- Local memory, session traces, reports, and job logs
- Support for LM Studio, Codex OAuth, and OpenAI-compatible providers
- Operational dashboard for status, jobs, sessions, and replay
- Background service controls for the Telegram bot runtime

## Requirements

- Node.js `>= 24`
- Python environment for the core runtime under `taxsentry-core/`
- GitHub access if you want to publish or push releases

## Install

### Global install from npm

```bash
npm install -g taxsentry
```

### Local development

```bash
npm install
npm test
```

If you run the repository locally, the Node CLI will call into the Python core under `taxsentry-core/`.

## First Run

```bash
taxsentry setup
```

Useful follow-up commands:

```bash
taxsentry start
taxsentry status
taxsentry doctor
taxsentry dashboard
taxsentry jobs
taxsentry replay
taxsentry reconfigure
taxsentry reset-profile
```

## Main Workflows

### Interactive cockpit

```bash
taxsentry start
```

This opens the Hermes-style terminal cockpit.

### Operational dashboard

```bash
taxsentry dashboard
```

Use this to inspect provider health, recent jobs, recent sessions, and trace replay information.

### Background service

```bash
taxsentry up
taxsentry stop
taxsentry service status
taxsentry service install
taxsentry service apply
```

The `service` command family manages the Telegram bot service artifacts and OS registration.

## CLI Reference

### Core commands

| Command | Purpose |
| --- | --- |
| `taxsentry setup` | Run the provider-first onboarding wizard |
| `taxsentry start` | Open the interactive terminal cockpit |
| `taxsentry status` | Show saved configuration and provider health |
| `taxsentry doctor` | Run a runtime health check |
| `taxsentry dashboard` | Open the operational dashboard |
| `taxsentry jobs` | Show recent jobs and their states |
| `taxsentry replay [session_id]` | Replay a session trace, or choose one from the recent list |
| `taxsentry reconfigure` | Re-run onboarding without wiping secrets |
| `taxsentry reset-profile` | Reset the local profile and onboarding state |
| `taxsentry auth codex` | Link the current configuration to Codex OAuth |
| `taxsentry update` | Refresh runtime config or self-update the installed package |
| `taxsentry up` | Start the background agent in service mode |
| `taxsentry stop` | Stop the background agent |
| `taxsentry config` | Print the current saved configuration |

### Update commands

```bash
taxsentry update
taxsentry update --self
taxsentry update --config-only
taxsentry update --package-spec taxsentry@latest
```

### Service commands

| Command | Purpose |
| --- | --- |
| `taxsentry service` | Show service status |
| `taxsentry service status` | Show service artifact and registration status |
| `taxsentry service install` | Generate the platform-specific service artifact |
| `taxsentry service apply` | Apply the generated service artifact to the host OS |
| `taxsentry service start` | Start the registered OS service |
| `taxsentry service stop` | Stop the registered OS service |
| `taxsentry service restart` | Restart the registered OS service |
| `taxsentry service remove` | Remove the OS registration for the service |
| `taxsentry service remove --purge-artifacts` | Remove registration and delete generated service files |
| `taxsentry service logs -n 100` | Show the latest service logs |

## Agent Slash Commands

Inside the cockpit, these slash commands are available:

- `/help`
- `/status`
- `/memory`
- `/remember <text>`
- `/mode <chat|analysis|execute|review|setup>`
- `/provider`
- `/audit`
- `/tools`
- `/trace`
- `/dashboard`
- `/jobs`
- `/replay [session_id]`
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

TaxSentry keeps runtime state under the local TaxSentry home directory.

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
- `tests/` - Node smoke and regression tests
- `taxsentry-core/tests/` - Python regression tests

## Development

Run the common checks before shipping a change:

```bash
npm test
npm run lint
```

Run the Python core checks directly when you touch the runtime:

```bash
cd taxsentry-core
python -m pytest tests
```

## Publishing to npm

TaxSentry is configured as a public npm package.

### Release checklist

1. Make sure tests and lint pass:

```bash
npm test
npm run lint
```

2. Bump the package version:

```bash
npm version patch
```

Use `minor` or `major` if the release needs it.

3. Log in to npm if you have not already:

```bash
npm login
```

4. Publish the package:

```bash
npm publish --access public
```

Notes:

- `npm publish` will fail if the version already exists on npm, so always bump `package.json` first.
- This repository already has `prepublishOnly` configured, so `npm publish` runs tests and lint automatically.
- The package is already restricted to the intended OS targets in `package.json`.

### Recommended release flow

```bash
npm version patch
git push --follow-tags
npm publish --access public
```

## Notes

- `taxsentry start` is the main interactive entrypoint.
- `taxsentry update --self` is the supported self-update path for published npm installs.
- The `service` command family is focused on the Telegram bot runtime and OS registration.

## License

MIT
