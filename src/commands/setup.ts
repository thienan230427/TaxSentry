import chalk from 'chalk';
import inquirer from 'inquirer';

import { detectPython, getInstallInstructions, printDetectionResult } from '../utils/python-detector.ts';
import { runInstallation } from '../installer.ts';
import { runOnboarding } from '../onboarding.ts';
import { isConfigured } from '../utils/paths.ts';

export async function runSetup({ resetExisting = false, prompt = inquirer.prompt.bind(inquirer) } = {}) {
  if (isConfigured() && !resetExisting) {
    const { overwrite } = await prompt([
      {
        type: 'confirm',
        name: 'overwrite',
        message: 'A previous TaxSentry config exists. Reconfigure it?',
        default: true,
      },
    ]);
    if (!overwrite) return { skipped: true };
  }

  const python = detectPython();
  printDetectionResult(python);
  if (!python.found) {
    console.log(chalk.hex('#93c5fd')('\n' + getInstallInstructions().join('\n')));
    throw new Error('Python 3.10+ is required to run TaxSentry.');
  }

  await runInstallation(python.command);
  const config = await runOnboarding({ resetExisting, prompt });
  return { skipped: false, config };
}

