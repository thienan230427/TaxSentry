# TaxSentry

TaxSentry is a provider-first local AI agent with a friendly setup wizard, persistent memory, and a cross-platform terminal UI.

It is designed to feel closer to a modern agent setup flow: choose a provider, pick a model, review defaults, and launch into a usable TUI without wrestling through a maze of flags.

## What changed

- Provider-first onboarding
- Friendly setup cards and guided prompts
- Local memory store for durable facts and recent conversations
- Support for:
  - LM Studio
  - OpenAI Codex OAuth
  - Any OpenAI-compatible endpoint
- Cross-platform launch paths for Windows, macOS, and Linux

## Quick start

```bash
npm install
npm run start
```

If this is your first run, TaxSentry will guide you through setup.

## Setup

```bash
taxsentry setup
```

The wizard lets you choose one of the supported provider modes:

- LM Studio for local-first inference
- OpenAI Codex OAuth if you already signed in with Codex
- Custom OpenAI-compatible endpoint for everything else

You can also reconfigure later:

```bash
taxsentry setup --reset
```

## Runtime commands

```bash
taxsentry start     # launch the interactive TUI
 taxsentry status   # print current config + provider health
 taxsentry doctor   # run a runtime health check
 taxsentry update   # refresh stored runtime config
 taxsentry update --self   # self-update the installed package from npm, then refresh config
 taxsentry memory list
 taxsentry memory add "remember this preference"
 taxsentry auth codex
```

## Provider support

### LM Studio

Set:

- Base URL: `http://localhost:1234/v1`
- Model: any model available in LM Studio
- API key: optional, usually blank for local servers

### Codex OAuth

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

- `bin/taxsentry.js` — CLI entrypoint
- `src/` — Node orchestration, setup, and launcher logic
- `taxsentry-core/src/taxsentry/` — Python runtime, memory store, provider abstraction, and TUI

## Packaging

The project is published as an npm package so the CLI is easy to install on:

- Windows
- macOS
- Linux

Publishing is guarded by smoke tests that verify the tarball contents and secret handling.

## License

MIT
