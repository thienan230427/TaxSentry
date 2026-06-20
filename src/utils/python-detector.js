/**
 * 🛡️ TaxSentry CLI - Python Detector
 * Automatically finds Python 3.10+ on the system across platforms.
 */

import { execSync } from 'child_process';
import { existsSync } from 'fs';
import { join } from 'path';
import chalk from 'chalk';

const MIN_PYTHON_VERSION = { major: 3, minor: 10 };

/**
 * Parse a Python version string like "Python 3.12.4" into { major, minor, patch }.
 */
export function parseVersion(versionStr) {
  const match = versionStr.match(/Python\s+(\d+)\.(\d+)\.(\d+)/);
  if (!match) return null;
  return {
    major: parseInt(match[1], 10),
    minor: parseInt(match[2], 10),
    patch: parseInt(match[3], 10),
  };
}

/**
 * Check if a given version meets the minimum requirement.
 */
export function meetsRequirement(ver) {
  if (!ver) return false;
  if (ver.major > MIN_PYTHON_VERSION.major) return true;
  if (ver.major === MIN_PYTHON_VERSION.major && ver.minor >= MIN_PYTHON_VERSION.minor) return true;
  return false;
}

/**
 * Try to get Python version from a specific command.
 */
function tryPythonCommand(cmd) {
  try {
    const output = execSync(`${cmd} --version`, {
      stdio: ['pipe', 'pipe', 'pipe'],
      timeout: 5000,
    }).toString().trim();
    const ver = parseVersion(output);
    return ver ? { cmd, version: ver, raw: output } : null;
  } catch {
    return null;
  }
}

/**
 * Generate a list of python commands to try based on OS.
 */
function getPythonCommands() {
  const isWindows = process.platform === 'win32';
  if (isWindows) {
    // Windows: try python, python3, py launcher (with version hints)
    return ['python', 'python3', 'py -3.12', 'py -3.11', 'py -3.10', 'py'];
  }
  // Unix-like: try python3 first, then python
  return ['python3', 'python3.12', 'python3.11', 'python3.10', 'python'];
}

/**
 * Detect Python on the system. Returns an object:
 * { found: bool, command: string, version: {major, minor, patch}, raw: string }
 */
export function detectPython() {
  const commands = getPythonCommands();
  const results = [];

  for (const cmd of commands) {
    const result = tryPythonCommand(cmd);
    if (result && meetsRequirement(result.version)) {
      results.push(result);
    }
  }

  if (results.length === 0) {
    return { found: false, command: null, version: null, candidates: [] };
  }

  // Pick the highest version
  results.sort((a, b) => {
    if (a.version.major !== b.version.major) return b.version.major - a.version.major;
    return b.version.minor - a.version.minor;
  });

  const best = results[0];
  return {
    found: true,
    command: best.cmd,
    version: best.version,
    raw: best.raw,
    candidates: results,
  };
}

/**
 * Get installation instructions for Python based on OS.
 */
export function getInstallInstructions() {
  const isWindows = process.platform === 'win32';
  const isMac = process.platform === 'darwin';

  const instructions = ['🐍 TaxSentry yêu cầu Python >= 3.10. Vui lòng cài đặt:', ''];

  if (isWindows) {
    instructions.push(
      chalk.bold('   Windows (chọn 1 trong 3):'),
      chalk.yellow('   • winget install Python.Python.3.12'),
      chalk.yellow('   • Tải từ: https://www.python.org/downloads/windows/'),
      chalk.yellow('   • Microsoft Store: tìm "Python 3.12"'),
      '',
      chalk.dim('   ⚠️ Quan trọng: Tick vào "Add python.exe to PATH" khi cài đặt!'),
    );
  } else if (isMac) {
    instructions.push(
      chalk.bold('   macOS (chọn 1 trong 2):'),
      chalk.yellow('   • brew install python@3.12'),
      chalk.yellow('   • Tải từ: https://www.python.org/downloads/macos/'),
    );
  } else {
    instructions.push(
      chalk.bold('   Linux:'),
      chalk.yellow('   • Ubuntu/Debian: sudo apt install python3.12'),
      chalk.yellow('   • Fedora: sudo dnf install python3.12'),
      chalk.yellow('   • Arch: sudo pacman -S python'),
    );
  }

  return instructions;
}

/**
 * Pretty-print detection result.
 */
export function printDetectionResult(result) {
  if (result.found) {
    console.log(chalk.green(`   ✅ Tìm thấy Python ${result.version.major}.${result.version.minor}.${result.version.patch}`));
    console.log(chalk.dim(`      → Command: ${result.command}`));
  } else {
    console.log(chalk.red('   ❌ Không tìm thấy Python 3.10+ trên hệ thống!'));
  }
}
