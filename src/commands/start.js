import chalk from 'chalk';

import { startForeground } from '../launcher.js';
import { isConfigured } from '../utils/paths.js';
import { runSetup } from './setup.js';

export default async function startCommand() {
  if (!isConfigured()) {
    console.log(chalk.yellow('No configuration found yet — launching setup first.'));
    await runSetup({ resetExisting: true });
  }
  console.log(chalk.cyan('Launching the TaxSentry agent TUI...'));
  const exitCode = startForeground(['tui']);
  if (exitCode !== 0) {
    process.exitCode = exitCode;
  }
}
