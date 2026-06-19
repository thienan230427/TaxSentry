/**
 * 🛡️ TaxSentry CLI - Python Launcher
 * Spawn Python subprocesses for TUI and Bot, handling cross-platform concerns.
 */

import { spawn, spawnSync } from 'child_process';
import { writeFileSync, readFileSync, existsSync, mkdirSync, rmSync, openSync } from 'fs';
import { join } from 'path';
import { getPythonPath, RUN_DIR, CORE_DIR, LOGS_DIR, ensureDirectories } from './utils/paths.js';
import { info, success, error, warn, debug } from './utils/logger.js';
import chalk from 'chalk';

/**
 * Get the path to the PID file for a given service.
 */
function getPidFile(serviceName) {
  return join(RUN_DIR, `${serviceName}.pid`);
}

/**
 * Get the path to the log file for a given service.
 */
function getLogFile(serviceName) {
  return join(LOGS_DIR, `${serviceName}.log`);
}

/**
 * Determine the correct working directory for the Python process.
 * In development, use the project root's taxsentry-core.
 * In production, use ~/.taxsentry/taxsentry-core.
 */
function getPythonWorkingDir() {
  // Dev mode: if we're in the repo, use taxsentry-core relative to CWD
  const devCoreDir = join(process.cwd(), 'taxsentry-core');
  if (existsSync(join(devCoreDir, 'pyproject.toml'))) {
    return devCoreDir;
  }
  
  // Prod mode: use installed core directory
  return CORE_DIR;
}

/**
 * Determine the correct Python executable path.
 * In development, use the venv in project root.
 * In production, use ~/.taxsentry/.venv.
 */
function getPythonExecutable() {
  const devPythonPath = join(process.cwd(), '.venv', 
    process.platform === 'win32' ? 'Scripts' : 'bin',
    process.platform === 'win32' ? 'python.exe' : 'python'
  );
  if (existsSync(devPythonPath)) {
    return devPythonPath;
  }
  return getPythonPath();
}

/**
 * Start a Python process in FOREGROUND with stdio inherited (for TUI).
 * Returns the exit code when the process exits.
 */
export function startForeground(args = ['-m', 'taxsentry']) {
  const pyPath = getPythonExecutable();
  const cwd = getPythonWorkingDir();

  if (!existsSync(pyPath)) {
    error(`Không tìm thấy Python tại: ${pyPath}`);
    error('Vui lòng chạy `taxsentry setup` trước.');
    process.exit(1);
  }

  info(`Đang khởi chạy Python TUI từ: ${pyPath}`);
  debug(`Working directory: ${cwd}`, true);
  debug(`Args: ${args.join(' ')}`, true);

  try {
    const result = spawnSync(pyPath, args, {
      cwd,
      stdio: 'inherit', // Allow Rich TUI to render properly
      env: process.env,
    });

    return result.status ?? 0;
  } catch (err) {
    error(`Lỗi khi chạy Python: ${err.message}`);
    return 1;
  }
}

/**
 * Start a Python process in BACKGROUND, attached to parent lifecycle.
 * Unlike startBackground(), this one does NOT use detached mode,
 * so when the terminal closes, the child process dies automatically.
 * Returns the child process reference on success, null on failure.
 */
export function startAttached(serviceName, args) {
  const pyPath = getPythonExecutable();
  const cwd = getPythonWorkingDir();
  const logFile = getLogFile(serviceName);
  const pidFile = getPidFile(serviceName);

  ensureDirectories();

  if (!existsSync(pyPath)) {
    error(`Không tìm thấy Python tại: ${pyPath}`);
    return null;
  }

  // Check if already running
  if (isRunning(serviceName)) {
    warn(`Dịch vụ '${serviceName}' đang chạy với PID: ${getPid(serviceName)}`);
    return null;
  }

  info(`Đang khởi chạy ${serviceName} ở chế độ nền (attached)...`);
  debug(`Args: ${args.join(' ')}`, true);

  const logStream = openSync(logFile, 'a');

  const child = spawn(pyPath, args, {
    cwd,
    stdio: ['ignore', logStream, logStream],
    detached: false, // NOT detached → dies when terminal closes
    env: {
      ...process.env,
      PYTHONPATH: `${cwd}\\src${process.env.PYTHONPATH ? `;${process.env.PYTHONPATH}` : ''}`,
    },
  });

  // Don't unref — keep reference for cleanup

  if (child.pid) {
    writeFileSync(pidFile, child.pid.toString(), 'utf-8');
    success(`${serviceName} được khởi chạy ở chế độ nền (PID: ${child.pid})`);
    return child;
  } else {
    error('Không thể lấy PID của tiến trình nền.');
    return null;
  }
}

/**
 * Start a Python process in BACKGROUND, detached, and log its PID.
 * Returns the PID on success, null on failure.
 */
export function startBackground(serviceName, args) {
  const pyPath = getPythonExecutable();
  const cwd = getPythonWorkingDir();
  const logFile = getLogFile(serviceName);
  const pidFile = getPidFile(serviceName);

  ensureDirectories();

  if (!existsSync(pyPath)) {
    error(`Không tìm thấy Python tại: ${pyPath}`);
    return null;
  }

  // Check if already running
  if (isRunning(serviceName)) {
    warn(`Dịch vụ '${serviceName}' đang chạy với PID: ${getPid(serviceName)}`);
    return getPid(serviceName);
  }

  info(`Đang khởi chạy ${serviceName} ở chế độ nền...`);
  debug(`Args: ${args.join(' ')}`, true);

  const logStream = openSync(logFile, 'a');
  
  const child = spawn(pyPath, args, {
    cwd,
    stdio: ['ignore', logStream, logStream],
    detached: true,
    env: {
      ...process.env,
      PYTHONPATH: `${cwd}\\src${process.env.PYTHONPATH ? `;${process.env.PYTHONPATH}` : ''}`,
    },
  });

  child.unref();

  if (child.pid) {
    writeFileSync(pidFile, child.pid.toString(), 'utf-8');
    success(`${serviceName} được khởi chạy ở chế độ nền (PID: ${child.pid})`);
    return child.pid;
  } else {
    error('Không thể lấy PID của tiến trình nền.');
    return null;
  }
}

/**
 * Read the PID for a given service.
 */
export function getPid(serviceName) {
  const pidFile = getPidFile(serviceName);
  if (!existsSync(pidFile)) return null;
  const pid = parseInt(readFileSync(pidFile, 'utf-8').trim(), 10);
  return isNaN(pid) ? null : pid;
}

/**
 * Check if a process with the given PID is running.
 * Works cross-platform using `process.kill(pid, 0)` - does NOT actually kill.
 */
export function isProcessRunning(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err.code === 'EPERM'; // Permission error = process exists but owned by another user
  }
}

/**
 * Check if a named service is currently running.
 */
export function isRunning(serviceName) {
  const pid = getPid(serviceName);
  return isProcessRunning(pid);
}

/**
 * Stop a named service by killing its PID.
 * Returns true on success, false on failure or if not running.
 */
export function stopService(serviceName) {
  const pid = getPid(serviceName);
  if (!pid || !isProcessRunning(pid)) {
    warn(`${serviceName} không đang chạy hoặc PID không hợp lệ.`);
    // Clean up stale PID file
    const pidFile = getPidFile(serviceName);
    if (existsSync(pidFile)) rmSync(pidFile);
    return false;
  }

  try {
    // Graceful: SIGTERM first
    process.kill(pid, 'SIGTERM');
    info(`Đã gửi tín hiệu tắt (SIGTERM) đến ${serviceName} (PID: ${pid}).`);

    // Wait a moment and check
    setTimeout(() => {
      if (isProcessRunning(pid)) {
        warn(`${serviceName} vẫn đang chạy. Đang buộc tắt (SIGKILL)...`);
        try {
          process.kill(pid, 'SIGKILL');
        } catch {
          // Ignore if already dead
        }
      }
    }, 2000);

    // Clean up PID file
    const pidFile = getPidFile(serviceName);
    if (existsSync(pidFile)) rmSync(pidFile);

    success(`Đã dừng ${serviceName} thành công.`);
    return true;
  } catch (err) {
    error(`Không thể dừng ${serviceName}: ${err.message}`);
    return false;
  }
}

/**
 * Get the status of a named service.
 */
export function getServiceStatus(serviceName) {
  const pid = getPid(serviceName);
  return {
    name: serviceName,
    running: isProcessRunning(pid),
    pid: pid,
    pidFile: getPidFile(serviceName),
    logFile: getLogFile(serviceName),
  };
}

/**
 * Print the tail of a service log file.
 */
export function tailLog(serviceName, lines = 20) {
  const logFile = getLogFile(serviceName);
  if (!existsSync(logFile)) {
    info(`Chưa có log nào cho ${serviceName}.`);
    return;
  }

  const content = readFileSync(logFile, 'utf-8');
  const allLines = content.split('\n').filter(l => l.length > 0);
  const tailLines = allLines.slice(-lines);

  console.log(chalk.gray(`\n── Last ${tailLines.length} lines of ${serviceName} log ──`));
  tailLines.forEach(line => console.log(chalk.dim(line)));
  console.log();
}
