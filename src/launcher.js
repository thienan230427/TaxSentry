import { closeSync, existsSync, openSync, readFileSync, unlinkSync, writeFileSync } from 'fs';
import { spawn, spawnSync } from 'child_process';
import { join } from 'path';

import { LOG_FILE, PID_FILE, CORE_DIR, getPythonPath, ensureDirectories } from './utils/paths.js';

function buildPythonEnv(extra = {}) {
  const env = { ...process.env, ...extra };
  env.PYTHONPATH = [
    join(CORE_DIR, 'src'),
    env.PYTHONPATH || '',
  ].filter(Boolean).join(process.platform === 'win32' ? ';' : ':');
  return env;
}

export function runPythonModule(args, { cwd = CORE_DIR, env = {}, background = false } = {}) {
  ensureDirectories();
  const python = getPythonPath();
  const commandArgs = ['-m', 'taxsentry', ...args];
  if (!background) {
    const result = spawn(python, commandArgs, {
      cwd,
      env: buildPythonEnv(env),
      stdio: 'inherit',
    });
    return result;
  }

  const logStream = openSync(LOG_FILE, 'a');
  const child = spawn(python, commandArgs, {
    cwd,
    env: buildPythonEnv(env),
    detached: true,
    stdio: ['ignore', logStream, logStream],
  });
  writeFileSync(PID_FILE, String(child.pid), 'utf8');
  child.unref();
  closeSync(logStream);
  return child;
}

export function startForeground(args = ['tui'], options = {}) {
  const python = getPythonPath();
  const commandArgs = ['-m', 'taxsentry', ...args];
  const result = spawnSync(python, commandArgs, {
    cwd: options.cwd || CORE_DIR,
    env: buildPythonEnv(options.env || {}),
    stdio: 'inherit',
  });
  return result.status ?? 0;
}

export function startBackground(args = ['tui'], options = {}) {
  runPythonModule(args, { ...options, background: true });
}

export function stopBackground() {
  if (!existsSync(PID_FILE)) return false;
  const pid = Number.parseInt(readFileSync(PID_FILE, 'utf8'), 10);
  if (Number.isNaN(pid)) {
    unlinkSync(PID_FILE);
    return false;
  }
  try {
    process.kill(pid);
  } catch {
    // already gone
  }
  unlinkSync(PID_FILE);
  return true;
}
