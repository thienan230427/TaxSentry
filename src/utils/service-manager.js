/**
 * 🛡️ TaxSentry CLI - Cross-platform Service Adapter Foundation
 * Provides platform-aware metadata for local background services and
 * leaves a clean seam for future systemd / launchd / Task Scheduler adapters.
 */

function getPlatformKey() {
  if (process.platform === 'win32') return 'windows';
  if (process.platform === 'darwin') return 'macos';
  return 'linux';
}

export function getPlatformServiceProfile() {
  const platform = getPlatformKey();

  if (platform === 'windows') {
    return {
      platform,
      manager: 'local-process',
      supervisor: 'Task Scheduler (future adapter)',
      detached: true,
      gracefulSignal: 'SIGTERM',
      forceSignal: 'SIGKILL',
      notes: 'Hiện dùng PID file + child process local; có thể nâng cấp sang Task Scheduler.',
    };
  }

  if (platform === 'macos') {
    return {
      platform,
      manager: 'local-process',
      supervisor: 'launchd (future adapter)',
      detached: true,
      gracefulSignal: 'SIGTERM',
      forceSignal: 'SIGKILL',
      notes: 'Hiện dùng PID file + child process local; phù hợp để nâng cấp sang launchd agent.',
    };
  }

  return {
    platform,
    manager: 'local-process',
    supervisor: 'systemd --user (future adapter)',
    detached: true,
    gracefulSignal: 'SIGTERM',
    forceSignal: 'SIGKILL',
    notes: 'Hiện dùng PID file + child process local; phù hợp để nâng cấp sang systemd user service.',
  };
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
    notes: profile.notes,
  };
}

export function formatServiceAdapterSummary(serviceName) {
  const adapter = getServiceAdapter(serviceName);
  return `${adapter.runtimeMode} | supervisor: ${adapter.recommendedSupervisor}`;
}
