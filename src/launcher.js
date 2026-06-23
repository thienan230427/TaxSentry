/**
 * 🛡️ TaxSentry CLI - Python Launcher
 * Spawn Python subprocesses for TUI and Bot, handling cross-platform concerns.
 */

import { spawn, spawnSync } from 'child_process';
import { writeFileSync, readFileSync, existsSync, rmSync, openSync } from 'fs';
import { join, delimiter } from 'path';
import { getPythonPath, RUN_DIR, CORE_DIR, LOGS_DIR, ensureDirectories } from './utils/paths.js';
import { getServiceAdapter } from './utils/service-manager.js';
import { info, success, error, warn, debug } from './utils/logger.js';
import chalk from 'chalk';

function getPidFile(serviceName) {
  return join(RUN_DIR, `${serviceName}.pid`);
}

function getLogFile(serviceName) {
  return join(LOGS_DIR, `${serviceName}.log`);
}

function getServiceCommandMarker(serviceName) {
  if (serviceName === 'telegram_bot') {
    return 'taxsentry.bot.telegram_bot';
  }
  return `taxsentry.${serviceName}`;
}

function getPythonWorkingDir() {
  const devCoreDir = join(process.cwd(), 'taxsentry-core');
  if (existsSync(join(devCoreDir, 'pyproject.toml'))) {
    return devCoreDir;
  }
  return CORE_DIR;
}

function getPythonExecutable() {
  const devPythonPath = join(
    process.cwd(),
    '.venv',
    process.platform === 'win32' ? 'Scripts' : 'bin',
    process.platform === 'win32' ? 'python.exe' : 'python',
  );
  if (existsSync(devPythonPath)) {
    return devPythonPath;
  }
  return getPythonPath();
}

function buildPythonEnv(cwd) {
  const srcPath = join(cwd, 'src');
  const existing = process.env.PYTHONPATH;
  return {
    ...process.env,
    PYTHONPATH: existing ? `${srcPath}${delimiter}${existing}` : srcPath,
  };
}

function parsePidList(output) {
  return String(output || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => parseInt(line, 10))
    .filter(pid => Number.isInteger(pid) && pid > 0);
}

function readPidFromFile(serviceName) {
  const pidFile = getPidFile(serviceName);
  if (!existsSync(pidFile)) return null;
  const pid = parseInt(readFileSync(pidFile, 'utf-8').trim(), 10);
  return Number.isInteger(pid) && pid > 0 ? pid : null;
}

function listServiceProcessPids(serviceName) {
  const marker = getServiceCommandMarker(serviceName);

  if (process.platform === 'win32') {
    const psScript = [
      '$ErrorActionPreference = "SilentlyContinue"',
      `$rows = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*${marker}*' } | Select-Object ProcessId, ParentProcessId`,
      '$parentIds = @($rows | ForEach-Object { $_.ParentProcessId })',
      '$leafRows = @($rows | Where-Object { $parentIds -notcontains $_.ProcessId })',
      'if ($leafRows.Count -gt 0) { $leafRows | Select-Object -ExpandProperty ProcessId } else { $rows | Select-Object -ExpandProperty ProcessId }'
    ].join('; ');
    const result = spawnSync('powershell.exe', ['-NoProfile', '-Command', psScript], { encoding: 'utf-8' });
    return parsePidList(result.stdout);
  }

  const result = spawnSync('ps', ['-ax', '-o', 'pid=,command='], { encoding: 'utf-8' });
  return String(result.stdout || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(line => line.includes(marker) && !line.includes('grep'))
    .map(line => parseInt(line.split(/\s+/, 1)[0], 10))
    .filter(pid => Number.isInteger(pid) && pid > 0);
}

function getTrackedServicePids(serviceName) {
  const discovered = listServiceProcessPids(serviceName);
  const filePid = readPidFromFile(serviceName);
  const merged = new Set(discovered);
  if (merged.size === 0 && filePid && isProcessRunning(filePid)) {
    merged.add(filePid);
  }
  return Array.from(merged).sort((a, b) => a - b);
}

function cleanupStalePidFile(serviceName) {
  const pidFile = getPidFile(serviceName);
  if (existsSync(pidFile)) {
    rmSync(pidFile, { force: true });
  }
}

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
      stdio: 'inherit',
      env: buildPythonEnv(cwd),
    });

    return result.status ?? 0;
  } catch (err) {
    error(`Lỗi khi chạy Python: ${err.message}`);
    return 1;
  }
}

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

  const existingPids = getTrackedServicePids(serviceName);
  if (existingPids.length > 0) {
    warn(`Dịch vụ '${serviceName}' đang chạy với PID(s): ${existingPids.join(', ')}`);
    return null;
  }

  info(`Đang khởi chạy ${serviceName} ở chế độ nền (attached)...`);
  debug(`Args: ${args.join(' ')}`, true);

  const logStream = openSync(logFile, 'a');
  const child = spawn(pyPath, args, {
    cwd,
    stdio: ['ignore', logStream, logStream],
    detached: false,
    env: buildPythonEnv(cwd),
  });

  if (child.pid) {
    writeFileSync(pidFile, child.pid.toString(), 'utf-8');
    success(`${serviceName} được khởi chạy ở chế độ nền (PID: ${child.pid})`);
    return child;
  }

  error('Không thể lấy PID của tiến trình nền.');
  return null;
}

export function startBackground(serviceName, args) {
  const pyPath = getPythonExecutable();
  const cwd = getPythonWorkingDir();
  const logFile = getLogFile(serviceName);
  const pidFile = getPidFile(serviceName);
  const adapter = getServiceAdapter(serviceName);

  ensureDirectories();

  if (!existsSync(pyPath)) {
    error(`Không tìm thấy Python tại: ${pyPath}`);
    return null;
  }

  const existingPids = getTrackedServicePids(serviceName);
  if (existingPids.length > 0) {
    warn(`Dịch vụ '${serviceName}' đang chạy với PID(s): ${existingPids.join(', ')}`);
    return existingPids[0];
  }

  info(`Đang khởi chạy ${serviceName} ở chế độ nền...`);
  debug(`Service adapter: ${adapter.runtimeMode} / ${adapter.recommendedSupervisor}`, true);
  debug(`Args: ${args.join(' ')}`, true);

  const logStream = openSync(logFile, 'a');
  const child = spawn(pyPath, args, {
    cwd,
    stdio: ['ignore', logStream, logStream],
    detached: adapter.detached,
    env: buildPythonEnv(cwd),
  });

  if (adapter.detached && typeof child.unref === 'function') {
    child.unref();
  }

  if (child.pid) {
    writeFileSync(pidFile, child.pid.toString(), 'utf-8');
    success(`${serviceName} được khởi chạy ở chế độ nền (PID: ${child.pid})`);
    return child.pid;
  }

  error('Không thể lấy PID của tiến trình nền.');
  return null;
}

export function getPid(serviceName) {
  const pids = getTrackedServicePids(serviceName);
  if (pids.length > 0) {
    return pids[0];
  }

  cleanupStalePidFile(serviceName);
  return null;
}

export function isProcessRunning(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err.code === 'EPERM';
  }
}

export function isRunning(serviceName) {
  return getTrackedServicePids(serviceName).length > 0;
}

export function stopService(serviceName) {
  const adapter = getServiceAdapter(serviceName);
  const pids = getTrackedServicePids(serviceName);

  if (pids.length === 0) {
    warn(`${serviceName} không đang chạy hoặc PID không hợp lệ.`);
    cleanupStalePidFile(serviceName);
    return false;
  }

  let stoppedAny = false;
  for (const pid of pids) {
    try {
      process.kill(pid, adapter.gracefulSignal);
      info(`Đã gửi tín hiệu tắt (${adapter.gracefulSignal}) đến ${serviceName} (PID: ${pid}).`);
      if (isProcessRunning(pid)) {
        try {
          process.kill(pid, adapter.forceSignal);
          info(`Đã buộc dừng ${serviceName} (PID: ${pid}) bằng ${adapter.forceSignal}.`);
        } catch {
          // ignore
        }
      }
      stoppedAny = true;
    } catch (err) {
      warn(`Không thể dừng ${serviceName} PID ${pid}: ${err.message}`);
    }
  }

  cleanupStalePidFile(serviceName);

  if (stoppedAny) {
    success(`Đã dừng ${serviceName} thành công.`);
  }
  return stoppedAny;
}

export function getServiceStatus(serviceName) {
  const pids = getTrackedServicePids(serviceName);
  return {
    name: serviceName,
    running: pids.length > 0,
    pid: pids[0] || null,
    pids,
    pidFile: getPidFile(serviceName),
    logFile: getLogFile(serviceName),
    discoveredViaProcessScan: pids.length > 0,
  };
}

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
