#!/usr/bin/env node
import { createRequire } from 'node:module';

import { Command } from 'commander';
import chalk from 'chalk';

import { runSetup } from '../src/commands/setup.js';
import startCommand from '../src/commands/start.js';
import statusCommand from '../src/commands/status.js';
import doctorCommand from '../src/commands/doctor.js';
import dashboardCommand from '../src/commands/dashboard.js';
import jobsCommand from '../src/commands/jobs.js';
import reconfigureCommand from '../src/commands/reconfigure.js';
import resetProfileCommand from '../src/commands/reset-profile.js';
import {
  applyServiceCommand,
  installServiceCommand,
  removeServiceCommand,
  restartServiceCommand,
  showServiceLogsCommand,
  showServiceStatus,
  startServiceCommand,
  stopServiceCommand,
} from '../src/commands/service.js';
import authCodexCommand from '../src/commands/auth-codex.js';
import updateCommand from '../src/commands/update.js';
import upCommand from '../src/commands/up.js';
import stopCommand from '../src/commands/stop.js';
import replayCommand from '../src/commands/replay.js';
import { loadConfig, describeConfig } from '../src/config.js';

const require = createRequire(import.meta.url);
const { version } = require('../package.json');

const program = new Command();
program
  .name('taxsentry')
  .description('TaxSentry — provider-first local AI agent. Use `taxsentry start` for the interactive TUI, `taxsentry update` to refresh config, and `taxsentry service` to manage background service artifacts.')
  .version(version)
  .addHelpText(
    'after',
    `
Primary commands:
  taxsentry setup   Run the provider-first setup wizard
  taxsentry start   Open the interactive TUI in the foreground
  taxsentry status  Show current configuration and provider health
  taxsentry doctor  Check runtime health
  taxsentry dashboard  Open the operational dashboard
  taxsentry jobs    Show recent jobs and their states
  taxsentry replay  Replay the latest session trace
  taxsentry reconfigure  Re-run onboarding without wiping secrets
  taxsentry reset-profile  Fully reset local profile and onboarding state
  taxsentry auth codex  Link the current configuration to Codex OAuth
  taxsentry update  Refresh runtime config or self-update the package
  taxsentry service  Manage Telegram bot service artifacts and OS registration
  taxsentry up      Start the background agent in service mode
  taxsentry stop    Stop the background agent
  taxsentry config  Print the current saved configuration

Examples:
  taxsentry setup --reset
  taxsentry start
  taxsentry service status
  taxsentry service install
  taxsentry up
  taxsentry status
  taxsentry update --self
`,
  );

program
  .command('setup')
  .description('Launch the provider-first setup wizard')
  .option('--reset', 'Reset and reconfigure from scratch', false)
  .action(async (opts) => {
    await runSetup({ resetExisting: Boolean(opts.reset) });
  });

program
  .command('start')
  .description('Launch the interactive agent TUI in the foreground')
  .action(startCommand);

program
  .command('status')
  .description('Show current configuration and provider health')
  .action(statusCommand);

program
  .command('doctor')
  .description('Check runtime health')
  .action(doctorCommand);

program
  .command('dashboard')
  .description('Open the operational dashboard')
  .action(dashboardCommand);

program
  .command('jobs')
  .description('Show recent jobs and their states')
  .action(jobsCommand);

program
  .command('replay')
  .description('Replay a session trace')
  .argument('[sessionId]', 'Session ID to replay')
  .action((sessionId) => {
    replayCommand(sessionId);
  });

program
  .command('reconfigure')
  .description('Re-run onboarding without wiping the existing local profile')
  .action(reconfigureCommand);

program
  .command('reset-profile')
  .description('Fully reset the local profile and rerun onboarding from scratch')
  .action(resetProfileCommand);

program
  .command('auth')
  .description('Authentication utilities')
  .command('codex')
  .description('Link the current configuration to Codex OAuth')
  .action(authCodexCommand);

program
  .command('update')
  .description('Refresh runtime config and optionally self-update the installed package')
  .option('--self', 'Install the latest TaxSentry package from npm before refreshing config')
  .option('--config-only', 'Refresh config without self-updating the package')
  .option('--package-spec <spec>', 'Package spec to install when self-updating', 'taxsentry@latest')
  .action(async (opts) => {
    await updateCommand({
      self: Boolean(opts.self && !opts.configOnly),
      packageSpec: opts.packageSpec,
    });
  });

program
  .command('up')
  .description('Start the background agent in service mode')
  .action(upCommand);

program
  .command('stop')
  .description('Stop the background agent')
  .action(stopCommand);

const service = program
  .command('service')
  .description('Manage the Telegram bot service artifacts and OS registration')
  .action(() => {
    showServiceStatus();
  });

service
  .command('status')
  .description('Show service artifact and registration status')
  .action(() => {
    showServiceStatus();
  });

service
  .command('install')
  .description('Generate the platform-specific service artifact')
  .action(() => {
    installServiceCommand();
  });

service
  .command('apply')
  .description('Apply the generated service artifact to the host OS')
  .action(() => {
    applyServiceCommand();
  });

service
  .command('start')
  .description('Start the registered OS service')
  .action(() => {
    startServiceCommand();
  });

service
  .command('stop')
  .description('Stop the registered OS service')
  .action(() => {
    stopServiceCommand();
  });

service
  .command('restart')
  .description('Restart the registered OS service')
  .action(() => {
    restartServiceCommand();
  });

service
  .command('remove')
  .description('Remove the service registration from the OS')
  .option('--purge-artifacts', 'Also delete local service artifact files', false)
  .action((opts) => {
    removeServiceCommand('telegram_bot', Boolean(opts.purgeArtifacts));
  });

service
  .command('logs')
  .description('Show recent service logs')
  .option('-n, --lines <count>', 'Number of log lines to print', '40')
  .action((opts) => {
    const lines = Number.parseInt(opts.lines, 10);
    showServiceLogsCommand('telegram_bot', Number.isNaN(lines) ? 40 : lines);
  });

program
  .command('config')
  .description('Print the current saved configuration')
  .action(() => {
    const config = loadConfig();
    console.log(chalk.bold.cyan('TaxSentry config'));
    console.log(describeConfig(config));
  });

program.parseAsync(process.argv).catch((error) => {
  console.error(chalk.red(error.stack || error.message || String(error)));
  process.exit(1);
});
