/**
 * 🛡️ TaxSentry CLI - Service Artifact Generator
 * Writes platform-specific service definitions for Linux, macOS, and Windows.
 */

import { existsSync, rmSync, writeFileSync } from 'fs';
import { join } from 'path';
import { CORE_DIR, LOGS_DIR, RUN_DIR, SERVICES_DIR, ensureDirectories, getPythonPath } from './paths.js';
import { getInstallHintLines, getPlatformServiceProfile, getServiceAdapter, getServiceLabel, getServiceModuleArgs } from './service-manager.js';

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
  const label = `com.taxsentry.${serviceName}`;
  const programArgs = args.map(arg => `    <string>${xmlEscape(arg)}</string>`).join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n<dict>\n  <key>Label</key>\n  <string>${label}</string>\n  <key>ProgramArguments</key>\n  <array>\n${programArgs}\n  </array>\n  <key>WorkingDirectory</key>\n  <string>${xmlEscape(CORE_DIR)}</string>\n  <key>EnvironmentVariables</key>\n  <dict>\n    <key>PYTHONPATH</key>\n    <string>${xmlEscape(join(CORE_DIR, 'src'))}</string>\n  </dict>\n  <key>RunAtLoad</key>\n  <true/>\n  <key>KeepAlive</key>\n  <true/>\n  <key>StandardOutPath</key>\n  <string>${xmlEscape(logPath)}</string>\n  <key>StandardErrorPath</key>\n  <string>${xmlEscape(logPath)}</string>\n</dict>\n</plist>\n`;
}

function renderWindowsTaskXml(serviceName, adminChatId = '') {
  const pythonPath = getPythonPath().replaceAll('/', '\\');
  const workingDir = CORE_DIR.replaceAll('/', '\\');
  const args = getServiceModuleArgs(serviceName, adminChatId).join(' ');
  const taskName = getServiceLabel(serviceName);

  return `<?xml version="1.0" encoding="UTF-8"?>\n<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n  <RegistrationInfo>\n    <Description>${xmlEscape(taskName)}</Description>\n  </RegistrationInfo>\n  <Triggers>\n    <LogonTrigger>\n      <Enabled>true</Enabled>\n    </LogonTrigger>\n  </Triggers>\n  <Principals>\n    <Principal id="Author">\n      <LogonType>InteractiveToken</LogonType>\n      <RunLevel>LeastPrivilege</RunLevel>\n    </Principal>\n  </Principals>\n  <Settings>\n    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n    <AllowHardTerminate>true</AllowHardTerminate>\n    <StartWhenAvailable>true</StartWhenAvailable>\n    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n    <IdleSettings>\n      <StopOnIdleEnd>false</StopOnIdleEnd>\n      <RestartOnIdle>false</RestartOnIdle>\n    </IdleSettings>\n    <AllowStartOnDemand>true</AllowStartOnDemand>\n    <Enabled>true</Enabled>\n    <Hidden>false</Hidden>\n    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n    <WakeToRun>false</WakeToRun>\n    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n    <Priority>7</Priority>\n  </Settings>\n  <Actions Context="Author">\n    <Exec>\n      <Command>${xmlEscape(pythonPath)}</Command>\n      <Arguments>${xmlEscape(args)}</Arguments>\n      <WorkingDirectory>${xmlEscape(workingDir)}</WorkingDirectory>\n    </Exec>\n  </Actions>\n</Task>\n`;
}

function renderWindowsInstallScript(serviceName) {
  const artifactPath = getServiceArtifactPath(serviceName).replaceAll('/', '\\');
  return `@echo off\r\nsetlocal\r\nschtasks /Create /TN "TaxSentry\\${serviceName}" /XML "${artifactPath}" /F\r\nschtasks /Run /TN "TaxSentry\\${serviceName}"\r\n`;
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
  writeFileSync(artifactPath, content, 'utf-8');

  const profile = getPlatformServiceProfile();
  let supportScriptPath = null;
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
  };
}

export function uninstallServiceArtifacts(serviceName) {
  const artifactPath = getServiceArtifactPath(serviceName);
  const supportScriptPath = getServiceSupportScriptPath(serviceName);

  if (existsSync(artifactPath)) {
    rmSync(artifactPath, { force: true });
  }
  if (existsSync(supportScriptPath)) {
    rmSync(supportScriptPath, { force: true });
  }

  return {
    artifactPath,
    supportScriptPath,
    removed: !existsSync(artifactPath) && !existsSync(supportScriptPath),
  };
}

export function getServiceArtifactPreview(serviceName) {
  const artifactPath = getServiceArtifactPath(serviceName);
  const supportScriptPath = getServiceSupportScriptPath(serviceName);
  return {
    artifactPath,
    supportScriptPath,
    artifactExists: existsSync(artifactPath),
    supportScriptExists: existsSync(supportScriptPath),
  };
}
