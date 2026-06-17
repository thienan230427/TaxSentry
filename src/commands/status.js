/**
 * 🛡️ TaxSentry CLI - Status Command
 * Shows system, Python, and service status.
 */

import { detectPython, printDetectionResult } from '../utils/python-detector.js';
import { isConfigured, loadConfig } from '../config.js';
import { getServiceStatus, isProcessRunning } from '../launcher.js';
import { info, success, warn } from '../utils/logger.js';
import chalk from 'chalk';

export default async function statusCommand() {
  console.log(chalk.bold.cyan('\n🛡️ TaxSentry System Status\n'));

  // 1. Python Status
  const py = detectPython();
  printDetectionResult(py);

  // 2. Configuration Status
  console.log();
  if (isConfigured()) {
    success('Cấu hình: Đã được thiết lập ✅');
    const config = loadConfig();
    console.log(chalk.dim(`   → Director: ${config.directorName}`));
    if (config.telegramBotToken) {
      console.log(chalk.dim(`   → Telegram: @${config.telegramBotToken.split(':')[0]}...`));
    }
    if (config.mysql) {
      console.log(chalk.dim(`   → Database: ${config.mysql.user}@${config.mysql.host}:${config.mysql.port}/${config.mysql.database}`));
    }
  } else {
    warn('Cấu hình: Chưa thiết lập ❌ (chạy `taxsentry setup`)');
  }

  // 3. Service Status
  console.log();
  console.log(chalk.bold.cyan('Trạng thái dịch vụ:'));
  const botStatus = getServiceStatus('telegram_bot');
  if (botStatus.running) {
    success(`   Telegram Bot: Đang chạy (PID: ${botStatus.pid})`);
  } else {
    warn(`   Telegram Bot: Không đang chạy`);
  }

  console.log();
}
