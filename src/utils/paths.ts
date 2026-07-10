import { existsSync, mkdirSync } from "fs";
import { homedir } from "os";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const PACKAGE_ROOT = join(HERE, "..", "..");
export const BUNDLED_CORE_DIR = join(PACKAGE_ROOT, "taxsentry-core");

export const TAXSENTRY_HOME = join(homedir(), ".taxsentry");
export const CONFIG_DIR = join(TAXSENTRY_HOME, "config");
export const MEMORY_DIR = join(TAXSENTRY_HOME, "memory");
export const LOGS_DIR = join(TAXSENTRY_HOME, "logs");
export const RUN_DIR = join(TAXSENTRY_HOME, "run");
export const SERVICES_DIR = join(TAXSENTRY_HOME, "services");
export const VENV_DIR = join(TAXSENTRY_HOME, ".venv");
export const CORE_DIR = join(TAXSENTRY_HOME, "taxsentry-core");

export const CONFIG_FILE = join(CONFIG_DIR, "config.json");
export const ENV_FILE = join(CORE_DIR, ".env");
export const MEMORY_DB_FILE = join(MEMORY_DIR, "memory.db");
export const SESSION_FILE = join(MEMORY_DIR, "sessions.jsonl");
export const PID_FILE = join(RUN_DIR, "taxsentry.pid");
export const LOG_FILE = join(LOGS_DIR, "taxsentry.log");

export function ensureDirectories() {
  for (const dir of [TAXSENTRY_HOME, CONFIG_DIR, MEMORY_DIR, LOGS_DIR, RUN_DIR, SERVICES_DIR, CORE_DIR]) {
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
  }
}

export function getPythonPath() {
  return process.platform === "win32"
    ? join(VENV_DIR, "Scripts", "python.exe")
    : join(VENV_DIR, "bin", "python");
}

export function getPipPath() {
  return process.platform === "win32"
    ? join(VENV_DIR, "Scripts", "pip.exe")
    : join(VENV_DIR, "bin", "pip");
}

export function isConfigured() {
  return existsSync(CONFIG_FILE) && existsSync(ENV_FILE);
}
