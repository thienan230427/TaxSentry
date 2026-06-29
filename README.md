# TaxSentry

TaxSentry is a local-first AI audit agent for founders, directors, finance teams, and SMEs that need better visibility into financial and tax risk without sending sensitive data to a third-party SaaS by default.

In practical terms, TaxSentry ingests incoming reports, reads spreadsheets and PDFs, analyzes risk signals with an AI model you control, and sends clear, actionable summaries through Telegram. Your team keeps control of the data, the runtime, and the operating model.

## What problem does TaxSentry solve?

In many small and mid-sized businesses, finance and tax review is still fragmented:
- reports arrive by email as Excel or PDF files
- managers only review them when someone remembers to follow up
- tax risk is often detected too late
- data lives in too many places to monitor continuously

TaxSentry turns that into a cleaner operating flow:
- receive reports from email
- read Excel and PDF attachments
- normalize the data for downstream processing
- analyze risk with a local AI model
- send alerts and summaries to Telegram
- run through a CLI or as a background service

## Why teams choose TaxSentry

TaxSentry is not just "AI added on top." It is built to be usable in real operations:
- sensitive data stays local instead of being pushed to the cloud by default
- the CLI is explicit, scriptable, and easy to automate
- the bot can run as a background process instead of being started manually every time
- configuration is flexible, so teams are not locked into a rigid hardcoded schema
- it works well for operators who want control over runtime behavior instead of relying entirely on a web dashboard

## Who it is for

TaxSentry is a strong fit for:
- directors who want finance and tax alerts in Telegram
- founders or COOs who want a lighter operational monitoring layer
- internal finance teams that need an additional review and follow-up tool
- businesses that care about privacy, local-first workflows, and control over infrastructure

If you want a fully managed "sign up and everything runs for you" SaaS, TaxSentry is not positioned that way today. It is designed for organizations that prefer control, self-hosted operation, and on-premise deployment.

## Current capabilities

The current release includes:
- inbound report collection via IMAP email
- Excel and PDF parsing
- analysis with a local LLM or an OpenAI-compatible endpoint such as LM Studio
- optional Codex OAuth auth mode via `~/.codex/auth.json` for users who do not want to paste an API key manually
- Telegram bot delivery for alerts, summaries, and interactive workflows
- runtime commands such as `setup`, `auth codex`, `update`, `status`, `up`, `bot`, and `stop`
- service workflows, including Windows Task Scheduler integration
- flexible configuration commands that let you add, rename, and remove fields without editing source code for every small change

## Requirements

TaxSentry currently requires:
- Node.js 24+
- Python 3.10+
- MySQL
- a Telegram bot token from @BotFather
- a local AI endpoint if you want local LLM analysis, such as LM Studio, or an existing Codex OAuth profile at `~/.codex/auth.json`

## Installation

You can use TaxSentry either from npm or from source.

### Option 1: install from npm

```bash
npm install -g taxsentry
```

Or run it immediately without a global install:

```bash
npx taxsentry setup
```

### Option 2: run from source

```bash
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
npm install
node bin/taxsentry.js setup
```

## Windows setup

### 1. Install the required dependencies

Install Node.js 24+:

```powershell
winget install OpenJS.NodeJS
```

Install Python 3.10+:

```powershell
winget install Python.Python.3.12
```

Install MySQL:
- Use MySQL Installer or your preferred Windows package workflow.
- After installation, confirm that the MySQL service is running.

### 2. Install TaxSentry

```powershell
npm install -g taxsentry
```

Or run it directly:

```powershell
npx taxsentry setup
```

### 3. Run from source if needed

```powershell
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
npm install
node bin/taxsentry.js setup
```

## macOS setup

### 1. Install the required dependencies

If Homebrew is not installed yet, install it first from brew.sh.

Install Node.js 24+:

```bash
brew install node
```

Install Python 3.10+:

```bash
brew install python
```

Install and start MySQL:

```bash
brew install mysql
brew services start mysql
```

### 2. Install TaxSentry

```bash
npm install -g taxsentry
```

Or run it directly:

```bash
npx taxsentry setup
```

### 3. Run from source if needed

```bash
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
npm install
node bin/taxsentry.js setup
```

## Linux setup

TaxSentry supports Linux, but the package installation path depends on the distribution. The example below uses Ubuntu or Debian.

### 1. Install the required dependencies

```bash
sudo apt update
sudo apt install -y nodejs npm python3 python3-venv python3-pip mysql-server git
```

Some Linux repositories ship an outdated Node version. If that happens, install Node 24+ through `nvm` or NodeSource instead of relying on the distro default.

Example with `nvm`:

```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 24
nvm use 24
```

### 2. Install TaxSentry

```bash
npm install -g taxsentry
```

Or run it directly:

```bash
npx taxsentry setup
```

### 3. Run from source if needed

```bash
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
npm install
node bin/taxsentry.js setup
```

## Quick start

### 1. Run the setup wizard

```bash
taxsentry setup
```

This command will:
- detect Python
- create a virtual environment in `~/.taxsentry/.venv`
- copy the Python core into the TaxSentry runtime home
- install Python dependencies
- launch the initial configuration wizard

### 2. Check system status

```bash
taxsentry status
```

Use this to confirm:
- whether Python was detected correctly
- whether configuration exists
- whether the Telegram bot is healthy
- whether service and runtime state look correct

### 3. Optional: switch AI auth to Codex OAuth

```bash
taxsentry auth codex
```

This command:
- reads `~/.codex/auth.json`
- validates that an access token exists
- switches TaxSentry to `ai.authMode=codex_oauth`
- keeps the OAuth token out of `config.json` and reads it live at runtime

### 4. Start the system

To run the full gateway flow:

```bash
taxsentry up
```

This starts:
- the TUI dashboard in the foreground
- the Telegram bot alongside it through the packaged runtime

If you only want the dashboard:

```bash
taxsentry start
```

If you only want the background bot:

```bash
taxsentry bot
```

### 5. Update TaxSentry safely from Git

```bash
taxsentry update
```

Update behavior:
- if the current package is a clean Git checkout, TaxSentry uses `git fetch` + `git pull --ff-only`
- if the current package has no `.git`, TaxSentry stages the latest source and replaces managed package paths safely
- after source refresh, TaxSentry syncs `~/.taxsentry/taxsentry-core` and refreshes Python dependencies
- if the working tree is dirty, the command aborts safely instead of creating merge conflicts

### 6. Stop the background runtime

```bash
taxsentry stop
```

## Service mode

If you want the bot to run more reliably at the operating-system level, TaxSentry includes a service workflow.

Check the current service definition:

```bash
taxsentry service status
```

Create service artifacts:

```bash
taxsentry service install
```

Apply the service to the OS:

```bash
taxsentry service apply
```

On Windows, this registers the bot in Task Scheduler.

Manage an applied service:

```bash
taxsentry service start
taxsentry service stop
taxsentry service restart
taxsentry service logs
```

Remove the service or local artifacts:

```bash
taxsentry service remove
taxsentry service uninstall
```

## Flexible configuration

One of TaxSentry's most practical strengths is that its configuration system is not hardwired.

Key commands:

```bash
taxsentry config
taxsentry config set <fieldPath> <value>
taxsentry config add-field <group> <key> <label>
taxsentry config rename-field <group> <oldKey> <newKey>
taxsentry config remove-field <group> <key>
taxsentry config add-group <id> <label>
taxsentry config env-map <fieldPath> <ENV_VAR>
taxsentry config generate-env
```

That gives each business room to adapt configuration fields without editing source code every time requirements change.

## A typical operating flow

A practical deployment usually looks like this:
1. run `taxsentry setup`
2. verify the environment with `taxsentry status`
3. start the system with `taxsentry up` or `taxsentry bot`
4. monitor runtime health with `taxsentry service status` and `taxsentry service logs`
5. if you want the OS to supervise the bot, use `taxsentry service install` and then `taxsentry service apply`

## Troubleshooting

### Setup cannot find Python

Install Python 3.10+ first, then run:

```bash
taxsentry setup
```

### npm is not authenticated

If you hit an auth error while publishing:

```bash
npm adduser
```

### `service apply` returns `access is denied` on Windows

Open the terminal with the required permissions and run:

```bash
taxsentry service apply
```

### The Telegram bot looks unhealthy

Check status and logs:

```bash
taxsentry status
taxsentry service logs
```

If needed, restart cleanly:

```bash
taxsentry stop
taxsentry bot
```

### You want to reset the runtime cleanly

```bash
taxsentry stop
taxsentry status
taxsentry bot
```

## Where TaxSentry stores data

Runtime data primarily lives in:
- `~/.taxsentry/`
- `~/.taxsentry/.venv/`
- `~/.taxsentry/taxsentry-core/`
- `~/.taxsentry/logs/`
- `~/.taxsentry/services/`
- `~/.taxsentry/run/`

## Product status

TaxSentry is well past the "just a prototype" stage. At the time this README was rewritten, the project already had:
- a public npm package: `taxsentry@0.1.1`
- a working public `npx taxsentry --version` flow
- a cleaner and more stable local runtime
- a verified Windows Task Scheduler service flow
- a cleaned npm tarball that no longer ships secrets or runtime artifacts

There is still room to polish the launch experience further, especially with screenshots, demo GIFs, English launch assets, and broader onboarding material. But the technical core and the packaging path are already in much better shape than an early-stage experiment.

## Security notes

TaxSentry is built with a local-first mindset, but local-first does not automatically mean risk-free.

Treat the following as sensitive data:
- `.env` files
- internal databases
- downloaded reports
- runtime logs
- output files that contain financial information

## Maintainer checklist

Before publishing a new release, at minimum verify:

```bash
npm pack --json
npm publish --dry-run
npm view taxsentry version dist-tags.latest
npx --yes taxsentry --version
```

## License

MIT
