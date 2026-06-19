/**
 * 🛡️ TaxSentry CLI - Service Artifact Generator
 * Writes platform-specific service definitions for Linux, macOS, and Windows,
 * and can register/remove them from the host OS.
 */

import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { spawnSync } from 'child_process';
import { CORE_DIR, LOGS_DIR, RUN_DIR, SERVICES_DIR, ensureDirectories, getPythonPath } from './paths.js';
import { getAppliedServiceName, getInstallHintLines, getPlatformServiceProfile, getServiceAdapter, getServiceLabel, getServiceModuleArgs } from './service-manager.js';

function xmlEscape(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

function shellQuote(value) {
  return `'${String(value).replaceAll(`'`, `'\\''`)}'`;
}

function runCommand(command, args) {
  const result = spawnSync(command, args, { encoding: 'utf-8' });
  return {
    status: result.status ?? 1,
    stdout: (result.stdout || '').trim(),
    stderr: (result.stderr || '').trim(),
    error: result.error ? result.error.message : null,
  };
}

function ensureParentDirectory(path) {
  mkdirSync(dirname(path), { recursive: true });
}

export function getServiceArtifactsDir() {
  ensureDirectories();
  return SERVICES_DIR;
}

export function getServiceArtifactPath(serviceName) {
  const adapter = getServiceAdapter(serviceName);
  return join(getServiceArtifactsDir(), `${serviceName}${adapter.artifactExtension}`);
}

export function getServiceSupportScriptPath(serviceName) {
  return join(getServiceArtifactsDir(), `${serviceName}.cmd`);
}

export function getAppliedServiceTargetPath(serviceName) {
  const profile = getPlatformServiceProfile();
  const appliedName = getAppliedServiceName(serviceName);

  if (profile.artifactType === 'systemd') {
    return join(process.env.HOME || '~', '.config', 'systemd', 'user', appliedName);
  }

  if (profile.artifactType === 'launchd') {
    return join(process.env.HOME || '~', 'Library', 'LaunchAgents', `${appliedName}.plist`);
  }

  return null;
}

function renderSystemdService(serviceName, adminChatId = '') {
  const pythonPath = getPythonPath();
  const label = getServiceLabel(serviceName);
  const logPath = join(LOGS_DIR, `${serviceName}.log`);
  const args = getServiceModuleArgs(serviceName, adminChatId).map(shellQuote).join(' ');

  return `[Unit]\nDescription=${label}\nAfter=network.target\n\n[Service]\nType=simple\nWorkingDirectory=${CORE_DIR}\nEnvironment=PYTHONPATH=${join(CORE_DIR, 'src')}\nExecStart=${pythonPath} ${args}\nRestart=on-failure\nRestartSec=5\nStandardOutput=append:${logPath}\nStandardError=append:${logPath}\n\n[Install]\nWantedBy=default.target\n`;
}

function renderLaunchdPlist(serviceName, adminChatId = '') {
  const pythonPath = getPythonPath();
  const args = [pythonPath, ...getServiceModuleArgs(serviceName, adminChatId)];
  const logPath = join(LOGS_DIR, `${serviceName}.log`);
  const label = getAppliedServiceName(serviceName);
  const programArgs = args.map(arg => `    <string>${xmlEscape(arg)}</string>`).join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n<dict>\n  <key>Label</key>\n  <string>${label}</string>\n  <key>ProgramArguments</key>\n  <array>\n${programArgs}\n  </array>\n  <key>WorkingDirectory</key>\n  <string>${xmlEscape(CORE_DIR)}</string>\n  <key>EnvironmentVariables</key>\n  <dict>\n    <key>PYTHONPATH</key>\n    <string>${xmlEscape(join(CORE_DIR, 'src'))}</string>\n  </dict>\n  <key>RunAtLoad</key>\n  <true/>\n  <key>KeepAlive</key>\n  <true/>\n  <key>StandardOutPath</key>\n  <string>${xmlEscape(logPath)}</string>\n  <key>StandardErrorPath</key>\n  <string>${xmlEscape(logPath)}</string>\n</dict>\n</plist>\n`;
}

function renderWindowsTaskXml(serviceName, adminChatId = '') {
  const pythonPath = getPythonPath().replaceAll('/', '\\');
  const workingDir = CORE_DIR.replaceAll('/', '\\');
  const args = getServiceModuleArgs(serviceName, adminChatId).join(' ');
  const taskName = getServiceLabel(serviceName);

  return `<?xml version="1.0" encoding="UTF-16"?>\n<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n  <RegistrationInfo>\n    <Description>${xmlEscape(taskName)}</Description>\n  </RegistrationInfo>\n  <Triggers>\n    <LogonTrigger>\n      <Enabled>true</Enabled>\n    </LogonTrigger>\n  </Triggers>\n  <Principals>\n    <Principal id="Author">\n      <LogonType>InteractiveToken</LogonType>\n      <RunLevel>LeastPrivilege</RunLevel>\n    </Principal>\n  </Principals>\n  <Settings>\n    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n    <AllowHardTerminate>true</AllowHardTerminate>\n    <StartWhenAvailable>true</StartWhenAvailable>\n    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n    <IdleSettings>\n      <StopOnIdleEnd>false</StopOnIdleEnd>\n      <RestartOnIdle>false</RestartOnIdle>\n    </IdleSettings>\n    <AllowStartOnDemand>true</AllowStartOnDemand>\n    <Enabled>true</Enabled>\n    <Hidden>false</Hidden>\n    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n    <WakeToRun>false</WakeToRun>\n    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n    <Priority>7</Priority>\n  </Settings>\n  <Actions Context="Author">\n    <Exec>\n      <Command>${xmlEscape(pythonPath)}</Command>\n      <Arguments>${xmlEscape(args)}</Arguments>\n      <WorkingDirectory>${xmlEscape(workingDir)}</WorkingDirectory>\n    </Exec>\n  </Actions>\n</Task>\n`;
}

function renderWindowsInstallScript(serviceName) {
  const artifactPath = getServiceArtifactPath(serviceName).replaceAll('/', '\\');
  const appliedName = getAppliedServiceName(serviceName);
  return `@echo off\r\nsetlocal\r\nschtasks /Create /TN "${appliedName}" /XML "${artifactPath}" /F\r\nschtasks /Run /TN "${appliedName}"\r\n`;
}

function writeArtifactFile(artifactPath, content, artifactType) {
  if (artifactType === 'task-scheduler') {
    writeFileSync(artifactPath, `\uFEFF${content}`, 'utf16le');
    return;
  }

  writeFileSync(artifactPath, content, 'utf-8');
}

export function generateServiceArtifactContent(serviceName, adminChatId = '') {
  const profile = getPlatformServiceProfile();
  if (profile.artifactType === 'systemd') {
    return renderSystemdService(serviceName, adminChatId);
  }
  if (profile.artifactType === 'launchd') {
    return renderLaunchdPlist(serviceName, adminChatId);
  }
  return renderWindowsTaskXml(serviceName, adminChatId);
}

export function installServiceArtifacts(serviceName, adminChatId = '') {
  ensureDirectories();
  const artifactPath = getServiceArtifactPath(serviceName);
  const content = generateServiceArtifactContent(serviceName, adminChatId);

  const profile = getPlatformServiceProfile();
  let supportScriptPath = null;
  writeArtifactFile(artifactPath, content, profile.artifactType);
  if (profile.artifactType === 'task-scheduler') {
    supportScriptPath = getServiceSupportScriptPath(serviceName);
    writeFileSync(supportScriptPath, renderWindowsInstallScript(serviceName), 'utf-8');
  }

  return {
    artifactPath,
    supportScriptPath,
    installHints: getInstallHintLines(serviceName, artifactPath),
    runtimeLogPath: join(LOGS_DIR, `${serviceName}.log`),
    runtimePidPath: join(RUN_DIR, `${serviceName}.pid`),
    appliedTargetPath: getAppliedServiceTargetPath(serviceName),
  };
}

export function uninstallServiceArtifacts(serviceName) {
  const artifactPath = getServiceArtifactPath(serviceName);
  const supportScriptPath = getServiceSupportScriptPath(serviceName);

  if (existsSync(artifactPath)) rmSync(artifactPath, { force: true });
  if (existsSync(supportScriptPath)) rmSync(supportScriptPath, { force: true });

  return {
    artifactPath,
    supportScriptPath,
    removed: !existsSync(artifactPath) && !existsSync(supportScriptPath),
  };
}

export function getServiceArtifactPreview(serviceName) {
  const artifactPath = getServiceArtifactPath(serviceName);
  const supportScriptPath = getServiceSupportScriptPath(serviceName);
  const appliedTargetPath = getAppliedServiceTargetPath(serviceName);
  return {
    artifactPath,
    supportScriptPath,
    appliedTargetPath,
    artifactExists: existsSync(artifactPath),
    supportScriptExists: existsSync(supportScriptPath),
    appliedTargetExists: appliedTargetPath ? existsSync(appliedTargetPath) : false,
  };
}

export function getAppliedServiceStatus(serviceName) {
  const profile = getPlatformServiceProfile();
  const appliedName = getAppliedServiceName(serviceName);

  if (profile.artifactType === 'task-scheduler') {
    const result = runCommand('schtasks', ['/Query', '/TN', appliedName]);
    return {
      registered: result.status === 0,
      active: result.status === 0,
      detail: result.stdout || result.stderr || result.error || 'Task chưa được đăng ký.',
      appliedName,
    };
  }

  if (profile.artifactType === 'systemd') {
    const enabled = runCommand('systemctl', ['--user', 'is-enabled', appliedName]);
    const active = runCommand('systemctl', ['--user', 'is-active', appliedName]);
    return {
      registered: enabled.status === 0 || active.status === 0,
      active: active.status === 0,
      detail: [enabled.stdout || enabled.stderr, active.stdout || active.stderr].filter(Boolean).join(' | ') || 'systemd user service chưa được đăng ký.',
      appliedName,
    };
  }

  const listed = runCommand('launchctl', ['list', appliedName]);
  return {
    registered: listed.status === 0,
    active: listed.status === 0,
    detail: listed.stdout || listed.stderr || listed.error || 'launchd agent chưa được nạp.',
    appliedName,
  };
}

export function applyServiceDefinition(serviceName, adminChatId = '') {
  const installResult = installServiceArtifacts(serviceName, adminChatId);
  const profile = getPlatformServiceProfile();
  const artifactPath = installResult.artifactPath;
  const appliedName = getAppliedServiceName(serviceName);

  if (profile.artifactType === 'task-scheduler') {
    const create = runCommand('schtasks', ['/Create', '/TN', appliedName, '/XML', artifactPath, '/F']);
    return {
      ok: create.status === 0,
      action: 'register',
      detail: create.stdout || create.stderr || create.error || '',
      installResult,
      appliedName,
    };
  }

  const targetPath = getAppliedServiceTargetPath(serviceName);
  ensureParentDirectory(targetPath);
  copyFileSync(artifactPath, targetPath);

  if (profile.artifactType === 'systemd') {
    const reload = runCommand('systemctl', ['--user', 'daemon-reload']);
    const enable = runCommand('systemctl', ['--user', 'enable', appliedName]);
    return {
      ok: reload.status === 0 && enable.status === 0,
      action: 'register',
      detail: [reload.stdout || reload.stderr, enable.stdout || enable.stderr].filter(Boolean).join(' | '),
      installResult,
      appliedName,
      targetPath,
    };
  }

  const unload = runCommand('launchctl', ['unload', targetPath]);
  const load = runCommand('launchctl', ['load', targetPath]);
  return {
    ok: load.status === 0,
    action: 'register',
    detail: [unload.stdout || unload.stderr, load.stdout || load.stderr].filter(Boolean).join(' | '),
    installResult,
    appliedName,
    targetPath,
  };
}

export function startAppliedService(serviceName) {
  const profile = getPlatformServiceProfile();
  const appliedName = getAppliedServiceName(serviceName);

  if (profile.artifactType === 'task-scheduler') {
    const start = runCommand('schtasks', ['/Run', '/TN', appliedName]);
    return {
      ok: start.status === 0,
      action: 'start',
      detail: start.stdout || start.stderr || start.error || '',
      appliedName,
    };
  }

  if (profile.artifactType === 'systemd') {
    const start = runCommand('systemctl', ['--user', 'start', appliedName]);
    return {
      ok: start.status === 0,
      action: 'start',
      detail: start.stdout || start.stderr || start.error || '',
      appliedName,
    };
  }

  const macDomain = `gui/${typeof process.getuid === 'function' ? process.getuid() : ''}/${appliedName}`;
  const kickstart = runCommand('launchctl', ['kickstart', '-k', macDomain]);
  return {
    ok: kickstart.status === 0,
    action: 'start',
    detail: kickstart.stdout || kickstart.stderr || kickstart.error || '',
    appliedName,
  };
}

export function stopAppliedService(serviceName) {
  const profile = getPlatformServiceProfile();
  const appliedName = getAppliedServiceName(serviceName);

  if (profile.artifactType === 'task-scheduler') {
    const stop = runCommand('schtasks', ['/End', '/TN', appliedName]);
    const detail = stop.stdout || stop.stderr || stop.error || '';
    const missing = /cannot find the file specified/i.test(detail);
    return {
      ok: stop.status === 0 || missing,
      action: 'stop',
      detail,
      appliedName,
    };
  }

  if (profile.artifactType === 'systemd') {
    const stop = runCommand('systemctl', ['--user', 'stop', appliedName]);
    return {
      ok: stop.status === 0,
      action: 'stop',
      detail: stop.stdout || stop.stderr || stop.error || '',
      appliedName,
    };
  }

  const stop = runCommand('launchctl', ['stop', appliedName]);
  return {
    ok: stop.status === 0,
    action: 'stop',
    detail: stop.stdout || stop.stderr || stop.error || '',
    appliedName,
  };
}

export function restartAppliedService(serviceName) {
  const profile = getPlatformServiceProfile();
  const appliedName = getAppliedServiceName(serviceName);

  if (profile.artifactType === 'task-scheduler') {
    const stop = runCommand('schtasks', ['/End', '/TN', appliedName]);
    const start = runCommand('schtasks', ['/Run', '/TN', appliedName]);
    const detail = [stop.stdout || stop.stderr, start.stdout || start.stderr || start.error].filter(Boolean).join(' | ');
    const missing = /cannot find the file specified/i.test(detail);
    return {
      ok: start.status === 0 || missing,
      action: 'restart',
      detail,
      appliedName,
    };
  }

  if (profile.artifactType === 'systemd') {
    const restart = runCommand('systemctl', ['--user', 'restart', appliedName]);
    return {
      ok: restart.status === 0,
      action: 'restart',
      detail: restart.stdout || restart.stderr || restart.error || '',
      appliedName,
    };
  }

  const macDomain = `gui/${typeof process.getuid === 'function' ? process.getuid() : ''}/${appliedName}`;
  const restart = runCommand('launchctl', ['kickstart', '-k', macDomain]);
  return {
    ok: restart.status === 0,
    action: 'restart',
    detail: restart.stdout || restart.stderr || restart.error || '',
    appliedName,
  };
}

export function removeAppliedService(serviceName) {
  const profile = getPlatformServiceProfile();
  const appliedName = getAppliedServiceName(serviceName);

  if (profile.artifactType === 'task-scheduler') {
    const remove = runCommand('schtasks', ['/Delete', '/TN', appliedName, '/F']);
    const detail = remove.stdout || remove.stderr || remove.error || '';
    const missing = /cannot find the file specified/i.test(detail);
    return {
      ok: remove.status === 0 || missing,
      action: 'remove',
      detail,
      appliedName,
    };
  }

  const targetPath = getAppliedServiceTargetPath(serviceName);

  if (profile.artifactType === 'systemd') {
    const disable = runCommand('systemctl', ['--user', 'disable', '--now', appliedName]);
    const reload = runCommand('systemctl', ['--user', 'daemon-reload']);
    if (targetPath && existsSync(targetPath)) rmSync(targetPath, { force: true });
    return {
      ok: disable.status === 0 || !existsSync(targetPath),
      action: 'remove',
      detail: [disable.stdout || disable.stderr, reload.stdout || reload.stderr].filter(Boolean).join(' | '),
      appliedName,
      targetPath,
    };
  }

  const unload = runCommand('launchctl', ['unload', targetPath]);
  if (targetPath && existsSync(targetPath)) rmSync(targetPath, { force: true });
  return {
    ok: unload.status === 0 || !existsSync(targetPath),
    action: 'remove',
    detail: unload.stdout || unload.stderr || unload.error || '',
    appliedName,
    targetPath,
  };
}

export function readServiceLog(serviceName, lines = 40) {
  const logPath = join(LOGS_DIR, `${serviceName}.log`);
  if (!existsSync(logPath)) {
    return {
      logPath,
      exists: false,
      lines: [],
    };
  }

  const content = readFileSync(logPath, 'utf-8');
  const tail = content.split(/\r?\n/).filter(Boolean).slice(-lines);
  return {
    logPath,
    exists: true,
    lines: tail,
  };
}
