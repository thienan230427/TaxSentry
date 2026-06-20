/**
 * 🛡️ TaxSentry CLI - Stop Command
 * Kills all background services (Bot, etc.).
 */

import { stopService, isRunning, getPid, getServiceStatus } from '../launcher.js';
import { isConfigured } from '../config.js';
import { info, success, warn, error } from '../utils/logger.js';
import chalk from 'chalk';

/**
 * Stop all running TaxSentry background services.
 */
export default async function stopCommand() {
  if (!isConfigured()) {
    warn('Chưa tìm thấy cấu hình. Không có dịch vụ nào đang chạy.');
    process.exit(0);
  }

  const services = ['telegram_bot'];
  let anyStopped = false;

  for (const service of services) {
    const status = getServiceStatus(service);
    if (status.running) {
      info(`Đang dừng ${service} (PID: ${status.pid})...`);
      if (stopService(service)) {
        anyStopped = true;
      }
    } else {
      info(`${service} không đang chạy.`);
    }
  }

  if (anyStopped) {
    success('Đã dừng tất cả các dịch vụ nền thành công. 👋');
  } else {
    success('Không có dịch vụ nền nào đang chạy.');
  }
}
