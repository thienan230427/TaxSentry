/**
 * 🛡️ TaxSentry CLI - Cross-platform Service Adapter Foundation
 * Provides platform-aware metadata for local background services and
 * a clean seam for future systemd / launchd / Task Scheduler adapters.
 */

function getPlatformKey(platform = process.platform) {
  if (platform === 'win32') return 'windows';
  if (platform === 'darwin') return 'macos';
  return 'linux';
}

function getSupervisorProfile(platform) {
  if (platform === 'windows') {
    return {
      manager: 'local-process',
      supervisor: 'Task Scheduler',
      detached: true,
      gracefulSignal: 'SIGTERM',
      forceSignal: 'SIGKILL',
      artifactType: 'task-scheduler',
      artifactExtension: '.xml',
      installScope: 'per-user',
      notes: 'Hiện dùng PID file + child process local; có thể nâng cấp sang Task Scheduler.',
    };
  }

  if (platform === 'macos') {
    return {
      manager: 'local-process',
      supervisor: 'launchd',
      detached: true,
      gracefulSignal: 'SIGTERM',
      forceSignal: 'SIGKILL',
      artifactType: 'launchd',
      artifactExtension: '.plist',
      installScope: 'per-user',
      notes: 'Hiện dùng PID file + child process local; phù hợp để nâng cấp sang launchd agent.',
    };
  }

  return {
    manager: 'local-process',
    supervisor: 'systemd --user',
    detached: true,
    gracefulSignal: 'SIGTERM',
    forceSignal: 'SIGKILL',
    artifactType: 'systemd',
    artifactExtension: '.service',
    installScope: 'per-user',
    notes: 'Hiện dùng PID file + child process local; phù hợp để nâng cấp sang systemd user service.',
  };
}

export function getServiceProfileForPlatform(platform = process.platform) {
  const normalizedPlatform = getPlatformKey(platform);
  return {
    platform: normalizedPlatform,
    ...getSupervisorProfile(normalizedPlatform),
  };
}

export function getPlatformServiceProfile() {
  return getServiceProfileForPlatform(process.platform);
}

export function getServiceAdapter(serviceName) {
  const profile = getPlatformServiceProfile();
  return {
    serviceName,
    runtimeMode: profile.manager,
    recommendedSupervisor: profile.supervisor,
    detached: profile.detached,
    gracefulSignal: profile.gracefulSignal,
    forceSignal: profile.forceSignal,
    artifactType: profile.artifactType,
    artifactExtension: profile.artifactExtension,
    installScope: profile.installScope,
    notes: profile.notes,
  };
}

export function formatServiceAdapterSummary(serviceName) {
  const adapter = getServiceAdapter(serviceName);
  return `${adapter.runtimeMode} | supervisor: ${adapter.recommendedSupervisor}`;
}

export function getServiceLabel(serviceName) {
  if (serviceName === 'telegram_bot') {
    return 'TaxSentry Telegram Bot';
  }
  return `TaxSentry ${serviceName}`;
}

export function getAppliedServiceNameForPlatform(platform = process.platform, serviceName) {
  const profile = getServiceProfileForPlatform(platform);

  if (profile.artifactType === 'launchd') {
    return `com.taxsentry.${serviceName}`;
  }

  if (profile.artifactType === 'systemd') {
    return `${serviceName}.service`;
  }

  return `TaxSentry-${serviceName}`;
}

export function getAppliedServiceName(serviceName) {
  return getAppliedServiceNameForPlatform(process.platform, serviceName);
}

export function getServiceModuleArgs(serviceName, adminChatId = '') {
  if (serviceName === 'telegram_bot') {
    const args = ['-m', 'taxsentry.bot.telegram_bot', '--with-automation-loop'];
    if (adminChatId) {
      args.push('--admin-chat-id', String(adminChatId));
    }
    return args;
  }

  return ['-m', 'taxsentry'];
}

export function getInstallHintLines(serviceName, artifactPath) {
  const adapter = getServiceAdapter(serviceName);
  const appliedName = getAppliedServiceName(serviceName);

  if (adapter.artifactType === 'systemd') {
    return [
      `mkdir -p ~/.config/systemd/user`,
      `cp "${artifactPath}" ~/.config/systemd/user/${appliedName}`,
      `systemctl --user daemon-reload`,
      `systemctl --user enable ${appliedName}`,
      `systemctl --user start ${appliedName}`,
    ];
  }

  if (adapter.artifactType === 'launchd') {
    return [
      `mkdir -p ~/Library/LaunchAgents`,
      `cp "${artifactPath}" ~/Library/LaunchAgents/${appliedName}.plist`,
      `launchctl unload ~/Library/LaunchAgents/${appliedName}.plist 2>/dev/null || true`,
      `launchctl load ~/Library/LaunchAgents/${appliedName}.plist`,
    ];
  }

  return [
    `schtasks /Create /TN "${appliedName}" /XML "${artifactPath}" /F`,
    `schtasks /Run /TN "${appliedName}"`,
  ];
}
