/**
 * 🛡️ TaxSentry CLI - Cross-platform Path Utilities
 * Handles consistent path resolution across Windows, macOS, and Linux.
 */

import { homedir } from 'os';
import { join } from 'path';
import { existsSync, mkdirSync } from 'fs';

// Root config directory: ~/.taxsentry
export const TAXSENTRY_HOME = join(homedir(), '.taxsentry');

// Sub-directories
export const CONFIG_DIR = join(TAXSENTRY_HOME, 'config');
export const LOGS_DIR = join(TAXSENTRY_HOME, 'logs');
export const RUN_DIR = join(TAXSENTRY_HOME, 'run');
export const VENV_DIR = join(TAXSENTRY_HOME, '.venv');
export const CORE_DIR = join(TAXSENTRY_HOME, 'taxsentry-core');
export const SERVICES_DIR = join(TAXSENTRY_HOME, 'services');

// Key files
export const CONFIG_FILE = join(CONFIG_DIR, 'config.json');
export const ENV_FILE = join(CORE_DIR, '.env');
export const PID_FILE = join(RUN_DIR, 'taxsentry.pid');
export const LOG_FILE = join(LOGS_DIR, 'taxsentry.log');

/**
 * Cross-platform Python executable path within the venv.
 * Windows: .venv\Scripts\python.exe
 * Unix:    .venv/bin/python
 */
export function getPythonPath() {
  const isWindows = process.platform === 'win32';
  return isWindows
    ? join(VENV_DIR, 'Scripts', 'python.exe')
    : join(VENV_DIR, 'bin', 'python');
}

/**
 * Cross-platform pip executable path within the venv.
 * Windows: .venv\Scripts\pip.exe
 * Unix:    .venv/bin/pip
 */
export function getPipPath() {
  const isWindows = process.platform === 'win32';
  return isWindows
    ? join(VENV_DIR, 'Scripts', 'pip.exe')
    : join(VENV_DIR, 'bin', 'pip');
}

/**
 * Ensure all TaxSentry directories exist.
 */
export function ensureDirectories() {
  const dirs = [TAXSENTRY_HOME, CONFIG_DIR, LOGS_DIR, RUN_DIR, CORE_DIR, SERVICES_DIR];
  for (const dir of dirs) {
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
  }
}

/**
 * Check if TaxSentry is already configured.
 */
export function isConfigured() {
  return existsSync(CONFIG_FILE) && existsSync(ENV_FILE);
}

/**
 * Get platform name for logging.
 */
export function getPlatformName() {
  const platform = process.platform;
  if (platform === 'win32') return 'Windows';
  if (platform === 'darwin') return 'macOS';
  return 'Linux';
}
