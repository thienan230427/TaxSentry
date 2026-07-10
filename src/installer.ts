import { cpSync, existsSync, mkdirSync, readdirSync } from "fs";
import { execFileSync } from "child_process";
import { join } from "path";

import chalk from "chalk";

import {
  BUNDLED_CORE_DIR,
  CORE_DIR,
  TAXSENTRY_HOME,
  ensureDirectories,
  getPipPath,
  getPythonPath,
} from "./utils/paths.ts";

function copyCoreSource() {
  if (!existsSync(BUNDLED_CORE_DIR)) {
    throw new Error(`Bundled taxsentry-core folder not found: ${BUNDLED_CORE_DIR}`);
  }

  mkdirSync(CORE_DIR, { recursive: true });
  const entries = readdirSync(BUNDLED_CORE_DIR, { withFileTypes: true });
  for (const entry of entries) {
    const src = join(BUNDLED_CORE_DIR, entry.name);
    const dst = join(CORE_DIR, entry.name);
    if (entry.isDirectory()) {
      cpSync(src, dst, {
        recursive: true,
        force: true,
        filter: (path) =>
          !path.endsWith(".db") &&
          !path.includes("__pycache__") &&
          !path.includes(".pytest_cache") &&
          !path.includes("downloads") &&
          !path.includes("scratch"),
      });
    } else if (entry.isFile()) {
      cpSync(src, dst, { force: true });
    }
  }
}

function createVenv(pythonCommand) {
  const python = pythonCommand || "python";
  if (existsSync(getPythonPath())) return;
  execFileSync(python, ["-m", "venv", join(TAXSENTRY_HOME, ".venv")], { stdio: "inherit" });
}

function installDependencies() {
  const pip = getPipPath();
  execFileSync(pip, ["install", "--upgrade", "pip"], { stdio: "inherit" });
  execFileSync(pip, ["install", "-r", join(CORE_DIR, "requirements.txt")], { stdio: "inherit" });
}

export async function runInstallation(pythonCommand = "python") {
  ensureDirectories();
  copyCoreSource();
  console.log(chalk.hex("#38bdf8")("Creating or reusing the TaxSentry venv..."));
  createVenv(pythonCommand);
  console.log(chalk.hex("#67e8f9")("Installing Python dependencies..."));
  installDependencies();
  return { pythonPath: getPythonPath() };
}

