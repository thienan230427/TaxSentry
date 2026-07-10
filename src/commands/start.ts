import chalk from 'chalk';

import { startForeground } from '../launcher.ts';
import { isConfigured } from '../utils/paths.ts';
import { runSetup } from './setup.ts';

export default async function startCommand() {
  if (!isConfigured()) {
    console.log(chalk.hex('#93c5fd')('No configuration found yet — launching setup first.'));
    await runSetup({ resetExisting: true });
  }
  console.log(chalk.hex('#38bdf8')('Launching the TaxSentry agent TUI...'));
  const exitCode = startForeground(['tui']);
  if (exitCode !== 0) {
    process.exitCode = exitCode;
  }
}

