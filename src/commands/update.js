import { execFileSync } from 'node:child_process';
import chalk from 'chalk';

import { loadConfig, saveConfig, writeEnvFile } from '../config.js';

export function refreshRuntimeConfig({ load = loadConfig, save = saveConfig, writeEnv = writeEnvFile } = {}) {
  const config = load();
  save(config);
  writeEnv(config);
  return config;
}

export function runSelfUpdate({ packageSpec = 'taxsentry@latest', runner = execFileSync } = {}) {
  runner('npm', ['install', '-g', packageSpec], { stdio: 'inherit' });
}

export default async function updateCommand(options = {}) {
  const {
    self = false,
    packageSpec = 'taxsentry@latest',
    runSelfUpdate: selfUpdateFn = runSelfUpdate,
    refreshRuntimeConfig: refreshFn = refreshRuntimeConfig,
  } = options;

  if (self) {
    await Promise.resolve(selfUpdateFn({ packageSpec }));
  }

  const config = await Promise.resolve(refreshFn());
  console.log(
    chalk.green(
      self
        ? 'TaxSentry self-update complete; runtime config refreshed.'
        : 'Runtime config refreshed. Re-run setup if you want to change provider/model.',
    ),
  );
  return config;
}
