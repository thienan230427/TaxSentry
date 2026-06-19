/**
 * 🛡️ TaxSentry CLI - Service Command
 * Generate/remove platform-specific service definitions for background bot runtime.
 */

import chalk from 'chalk';
import { isConfigured, loadConfig, getValue } from '../config.js';
import { getServiceArtifactPreview, installServiceArtifacts, uninstallServiceArtifacts } from '../utils/service-artifacts.js';
import { getServiceAdapter, getServiceLabel } from '../utils/service-manager.js';
import { info, success, warn } from '../utils/logger.js';

function resolveAdminChatId() {
  if (!isConfigured()) return '';
  const config = loadConfig();
  return getValue(config, 'telegram', 'adminChatId') || '';
}

export function showServiceStatus(serviceName = 'telegram_bot') {
  const adapter = getServiceAdapter(serviceName);
  const preview = getServiceArtifactPreview(serviceName);

  console.log(chalk.bold.cyan(`\n🧩 Service Definition: ${getServiceLabel(serviceName)}\n`));
  console.log(chalk.dim(`   Adapter: ${adapter.runtimeMode}`));
  console.log(chalk.dim(`   Supervisor đề xuất: ${adapter.recommendedSupervisor}`));
  console.log(chalk.dim(`   Scope: ${adapter.installScope}`));
  console.log(chalk.dim(`   Artifact chính: ${preview.artifactPath}`));
  console.log(chalk.dim(`   Đã tạo artifact: ${preview.artifactExists ? 'Có' : 'Chưa'}`));
  if (preview.supportScriptPath) {
    console.log(chalk.dim(`   Script hỗ trợ: ${preview.supportScriptPath}`));
    console.log(chalk.dim(`   Đã tạo script hỗ trợ: ${preview.supportScriptExists ? 'Có' : 'Chưa'}`));
  }
  console.log(chalk.dim(`   Ghi chú: ${adapter.notes}`));
  console.log();
}

export function installServiceCommand(serviceName = 'telegram_bot') {
  const adminChatId = resolveAdminChatId();
  if (!adminChatId) {
    warn('Chưa tìm thấy Admin Chat ID trong cấu hình. Artifact vẫn sẽ được tạo nhưng command bot sẽ thiếu tham số runtime cụ thể.');
  }

  const result = installServiceArtifacts(serviceName, adminChatId);
  success(`Đã tạo service artifact cho ${getServiceLabel(serviceName)}.`);
  console.log(chalk.dim(`   Artifact: ${result.artifactPath}`));
  if (result.supportScriptPath) {
    console.log(chalk.dim(`   Script hỗ trợ: ${result.supportScriptPath}`));
  }
  console.log(chalk.dim(`   Log runtime: ${result.runtimeLogPath}`));
  console.log(chalk.dim(`   PID runtime: ${result.runtimePidPath}`));
  console.log();
  info('Bước cài thủ công đề xuất:');
  for (const line of result.installHints) {
    console.log(chalk.dim(`   ${line}`));
  }
  console.log();
}

export function uninstallServiceCommand(serviceName = 'telegram_bot') {
  const result = uninstallServiceArtifacts(serviceName);
  if (result.removed) {
    success(`Đã gỡ artifact service cho ${getServiceLabel(serviceName)}.`);
  } else {
    warn(`Không thể xác nhận đã gỡ sạch artifact cho ${getServiceLabel(serviceName)}.`);
  }
  console.log(chalk.dim(`   Artifact: ${result.artifactPath}`));
  if (result.supportScriptPath) {
    console.log(chalk.dim(`   Script hỗ trợ: ${result.supportScriptPath}`));
  }
  console.log();
}
