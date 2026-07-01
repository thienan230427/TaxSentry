/**
 * 🛡️ TaxSentry CLI - Service Command
 * Generate/apply/remove platform-specific service definitions for background bot runtime.
 */

import chalk from 'chalk';
import { isConfigured, loadConfig, getValue } from '../config.js';
import {
  applyServiceDefinition,
  getAppliedServiceStatus,
  getServiceArtifactPreview,
  installServiceArtifacts,
  readServiceLog,
  removeAppliedService,
  restartAppliedService,
  startAppliedService,
  stopAppliedService,
  uninstallServiceArtifacts,
} from '../utils/service-artifacts.js';
import { getAppliedServiceName, getServiceAdapter, getServiceLabel } from '../utils/service-manager.js';
import { info, success, warn } from '../utils/logger.js';

function resolveAdminChatId() {
  if (!isConfigured()) return '';
  const config = loadConfig();
  return getValue(config, 'integrations', 'telegram')?.adminChatId || '';
}

export function showServiceStatus(serviceName = 'telegram_bot') {
  const adapter = getServiceAdapter(serviceName);
  const preview = getServiceArtifactPreview(serviceName);
  const applied = getAppliedServiceStatus(serviceName);

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
  if (preview.appliedTargetPath) {
    console.log(chalk.dim(`   Target OS file: ${preview.appliedTargetPath}`));
    console.log(chalk.dim(`   Target OS file tồn tại: ${preview.appliedTargetExists ? 'Có' : 'Chưa'}`));
  }
  console.log(chalk.dim(`   Tên đăng ký trên OS: ${getAppliedServiceName(serviceName)}`));
  console.log(chalk.dim(`   Đã apply vào OS: ${applied.registered ? 'Có' : 'Chưa'}`));
  console.log(chalk.dim(`   Trạng thái OS hiện tại: ${applied.active ? 'Active/Registered' : 'Chưa active'}`));
  if (applied.detail) {
    console.log(chalk.dim(`   Chi tiết OS: ${applied.detail}`));
  }
  console.log(chalk.dim(`   Ghi chú: ${adapter.notes}`));
  console.log();
}

export function installServiceCommand(serviceName = 'telegram_bot') {
  const adminChatId = resolveAdminChatId();
  if (!adminChatId) {
    warn('Chưa tìm thấy Admin Chat ID trong cấu hình. Artifact vẫn sẽ được tạo nhưng service runtime sẽ thiếu tham số chat cụ thể.');
  }

  const result = installServiceArtifacts(serviceName, adminChatId);
  success(`Đã tạo service artifact cho ${getServiceLabel(serviceName)}.`);
  console.log(chalk.dim(`   Artifact: ${result.artifactPath}`));
  if (result.supportScriptPath) {
    console.log(chalk.dim(`   Script hỗ trợ: ${result.supportScriptPath}`));
  }
  if (result.appliedTargetPath) {
    console.log(chalk.dim(`   Target OS file: ${result.appliedTargetPath}`));
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

export function applyServiceCommand(serviceName = 'telegram_bot') {
  const adminChatId = resolveAdminChatId();
  if (!adminChatId) {
    warn('Chưa tìm thấy Admin Chat ID trong cấu hình. Service vẫn sẽ được apply nhưng runtime có thể thiếu tham số chat cụ thể.');
  }

  const result = applyServiceDefinition(serviceName, adminChatId);
  if (result.ok) {
    success(`Đã apply service vào OS cho ${getServiceLabel(serviceName)}.`);
  } else {
    warn(`Apply service chưa hoàn tất trọn vẹn cho ${getServiceLabel(serviceName)}.`);
  }
  console.log(chalk.dim(`   Tên đăng ký: ${result.appliedName}`));
  if (result.installResult?.artifactPath) {
    console.log(chalk.dim(`   Artifact: ${result.installResult.artifactPath}`));
  }
  if (result.targetPath) {
    console.log(chalk.dim(`   Target OS file: ${result.targetPath}`));
  }
  if (result.detail) {
    console.log(chalk.dim(`   Chi tiết: ${result.detail}`));
    if (/access is denied/i.test(result.detail)) {
      console.log(chalk.yellow('   Gợi ý: hãy mở terminal với quyền phù hợp rồi chạy lại `taxsentry service apply`.'));
    }
  }
  console.log();
}

export function startServiceCommand(serviceName = 'telegram_bot') {
  const result = startAppliedService(serviceName);
  if (result.ok) {
    success(`Đã yêu cầu OS start service cho ${getServiceLabel(serviceName)}.`);
  } else {
    warn(`OS chưa start được service cho ${getServiceLabel(serviceName)}.`);
  }
  console.log(chalk.dim(`   Tên đăng ký: ${result.appliedName}`));
  if (result.detail) {
    console.log(chalk.dim(`   Chi tiết: ${result.detail}`));
  }
  console.log();
}

export function stopServiceCommand(serviceName = 'telegram_bot') {
  const result = stopAppliedService(serviceName);
  if (result.ok) {
    success(`Đã yêu cầu OS stop service cho ${getServiceLabel(serviceName)}.`);
  } else {
    warn(`OS chưa stop được service cho ${getServiceLabel(serviceName)}.`);
  }
  console.log(chalk.dim(`   Tên đăng ký: ${result.appliedName}`));
  if (result.detail) {
    console.log(chalk.dim(`   Chi tiết: ${result.detail}`));
  }
  console.log();
}

export function restartServiceCommand(serviceName = 'telegram_bot') {
  const result = restartAppliedService(serviceName);
  if (result.ok) {
    success(`Đã yêu cầu OS restart service cho ${getServiceLabel(serviceName)}.`);
  } else {
    warn(`OS chưa restart được service cho ${getServiceLabel(serviceName)}.`);
  }
  console.log(chalk.dim(`   Tên đăng ký: ${result.appliedName}`));
  if (result.detail) {
    console.log(chalk.dim(`   Chi tiết: ${result.detail}`));
  }
  console.log();
}

export function removeServiceCommand(serviceName = 'telegram_bot', purgeArtifacts = false) {
  const result = removeAppliedService(serviceName);
  if (result.ok) {
    success(`Đã gỡ service khỏi OS cho ${getServiceLabel(serviceName)}.`);
  } else {
    warn(`Không thể xác nhận đã gỡ service khỏi OS cho ${getServiceLabel(serviceName)}.`);
  }
  console.log(chalk.dim(`   Tên đăng ký: ${result.appliedName}`));
  if (result.targetPath) {
    console.log(chalk.dim(`   Target OS file: ${result.targetPath}`));
  }
  if (result.detail) {
    console.log(chalk.dim(`   Chi tiết: ${result.detail}`));
  }
  if (purgeArtifacts) {
    const purge = uninstallServiceArtifacts(serviceName);
    console.log(chalk.dim(`   Xóa artifact local: ${purge.removed ? 'Thành công' : 'Chưa xác nhận'}`));
  }
  console.log();
}

export function showServiceLogsCommand(serviceName = 'telegram_bot', lines = 40) {
  const result = readServiceLog(serviceName, lines);
  console.log(chalk.bold.cyan(`\n📜 Service Logs: ${getServiceLabel(serviceName)}\n`));
  console.log(chalk.dim(`   Log file: ${result.logPath}`));
  if (!result.exists) {
    warn('Chưa có log file để hiển thị.');
    console.log();
    return;
  }
  console.log(chalk.dim(`   Số dòng hiển thị: ${result.lines.length}`));
  const joined = result.lines.join('\n');
  if (/Conflict: terminated by other getUpdates request/i.test(joined)) {
    console.log(chalk.yellow('   Cảnh báo: bot đang bị Telegram polling conflict — có khả năng đang tồn tại instance khác của telegram_bot.'));
    console.log(chalk.yellow('   Gợi ý: chạy `taxsentry stop` để dọn bot local trước, rồi kiểm tra lại service apply/start.'));
  }
  console.log();
  for (const line of result.lines) {
    console.log(chalk.dim(line));
  }
  console.log();
}
