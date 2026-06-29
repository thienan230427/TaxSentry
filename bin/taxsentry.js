#!/usr/bin/env node
import { Command } from 'commander';
import chalk from 'chalk';
import figlet from 'figlet';

import { runSetup } from '../src/commands/setup.js';
import startCommand from '../src/commands/start.js';
import statusCommand from '../src/commands/status.js';
import doctorCommand from '../src/commands/doctor.js';
import authCodexCommand from '../src/commands/auth-codex.js';
import updateCommand from '../src/commands/update.js';
import botCommand from '../src/commands/bot.js';
import upCommand from '../src/commands/up.js';
import stopCommand from '../src/commands/stop.js';
import { loadConfig, describeConfig } from '../src/config.js';

const program = new Command();
program
  .name('taxsentry')
  .description('TaxSentry — a provider-first local AI agent with setup wizard and memory')
  .version('1.0.0');

program
  .command('setup')
  .description('Launch the provider-first setup wizard')
  .option('--reset', 'Reset and reconfigure from scratch', false)
  .action(async (opts) => {
    await runSetup({ resetExisting: Boolean(opts.reset) });
  });

program
  .command('start')
  .description('Launch the interactive agent TUI')
  .action(startCommand);

program
  .command('chat')
  .description('Alias for start')
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
  .command('auth')
  .description('Authentication utilities')
  .command('codex')
  .description('Link the current configuration to Codex OAuth')
  .action(authCodexCommand);

program
  .command('update')
  .description('Refresh the stored configuration files')
  .action(updateCommand);

program
  .command('bot')
  .description('Legacy alias for the interactive agent')
  .action(botCommand);

program
  .command('up')
  .description('Launch the interactive agent in the background')
  .action(upCommand);

program
  .command('stop')
  .description('Stop the background agent')
  .action(stopCommand);

program
  .command('config')
  .description('Print the current saved configuration')
  .action(() => {
    const config = loadConfig();
    console.log(chalk.bold.cyan('TaxSentry config'));
    console.log(describeConfig(config));
  });

program
  .command('banner')
  .description('Show the TaxSentry wordmark')
  .action(() => {
    console.log(chalk.cyan(figlet.textSync('TaxSentry', { horizontalLayout: 'full' })));
  });

program.parseAsync(process.argv).catch((error) => {
  console.error(chalk.red(error.stack || error.message || String(error)));
  process.exit(1);
});
