import chalk from 'chalk';
import inquirer from 'inquirer';

import { detectPython, getInstallInstructions, printDetectionResult } from './utils/python-detector.js';
import { runInstallation } from './installer.js';
import { runOnboarding } from './onboarding.js';
import { isConfigured } from './utils/paths.js';

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
    console.log(chalk.yellow('\n' + getInstallInstructions().join('\n')));
    throw new Error('Python 3.10+ is required to run TaxSentry.');
  }

  await runInstallation(python.command);
  const config = await runOnboarding({ resetExisting, prompt });
  return { skipped: false, config };
}
