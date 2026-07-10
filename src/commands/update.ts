import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import chalk from 'chalk';

import { loadConfig, saveConfig, writeEnvFile } from '../config.ts';

export function refreshRuntimeConfig({ load = loadConfig, save = saveConfig, writeEnv = writeEnvFile } = {}) {
  const config = load();
  save(config);
  writeEnv(config);
  return config;
}

export function resolveNpmCliPath() {
  const candidates = [];

  if (process.env.npm_execpath) {
    candidates.push(process.env.npm_execpath);
  }

  const nodeDir = dirname(process.execPath);
  candidates.push(join(nodeDir, 'node_modules', 'npm', 'bin', 'npm-cli.js'));
  candidates.push(join(nodeDir, '..', 'lib', 'node_modules', 'npm', 'bin', 'npm-cli.js'));
  candidates.push(join(nodeDir, '..', 'share', 'npm', 'bin', 'npm-cli.js'));

  for (const candidate of candidates) {
    if (candidate && existsSync(candidate)) {
      return candidate;
    }
  }

  return null;
}

export function runSelfUpdate({ packageSpec = 'taxsentry@latest', npmCliPath = resolveNpmCliPath(), runner = execFileSync } = {}) {
  const args = ['install', '-g', packageSpec];

  if (npmCliPath) {
    runner(process.execPath, [npmCliPath, ...args], {
      stdio: 'inherit',
    });
    return;
  }

  if (process.platform === 'win32') {
    runner('cmd.exe', ['/d', '/s', '/c', 'npm', ...args], {
      stdio: 'inherit',
    });
    return;
  }

  runner('npm', args, {
    stdio: 'inherit',
  });
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

