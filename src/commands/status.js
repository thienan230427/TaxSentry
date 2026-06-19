/**
 * 🛡️ TaxSentry CLI - Status Command
 * Shows system, Python, and service status.
 * Dùng new flexible config (getValue).
 */
import { detectPython, printDetectionResult } from '../utils/python-detector.js';
import { isConfigured, loadConfig, getValue } from '../config.js';
import { getPlatformName } from '../utils/paths.js';
import { getServiceAdapter, formatServiceAdapterSummary } from '../utils/service-manager.js';
import { getServiceStatus } from '../launcher.js';
import { success, warn } from '../utils/logger.js';
import chalk from 'chalk';

export default async function statusCommand() {
  console.log(chalk.bold.cyan('\n🛡️ TaxSentry System Status\n'));

  // 1. Python Status
  const py = detectPython();
  printDetectionResult(py);

  // 2. Runtime Platform
  console.log();
  console.log(chalk.bold.cyan('Nền tảng runtime:'));
  console.log(chalk.dim(`   → OS hiện tại: ${getPlatformName()}`));
  const platformAdapter = getServiceAdapter('telegram_bot');
  console.log(chalk.dim(`   → Service adapter: ${formatServiceAdapterSummary('telegram_bot')}`));
  console.log(chalk.dim(`   → Ghi chú: ${platformAdapter.notes}`));

  // 3. Configuration Status
  console.log();
  if (isConfigured()) {
    success('Cấu hình: Đã được thiết lập ✅');
    const config = loadConfig();
    const directorName = getValue(config, 'director', 'directorName');
    const botToken = getValue(config, 'telegram', 'telegramBotToken');
    const dbHost = getValue(config, 'mysql', 'host');
    const dbUser = getValue(config, 'mysql', 'user');
    const dbPort = getValue(config, 'mysql', 'port');
    const dbName = getValue(config, 'mysql', 'database');

    console.log(chalk.dim(`   → Director: ${directorName}`));
    if (botToken) {
      console.log(chalk.dim(`   → Telegram: @${botToken.split(':')[0]}...`));
    }
    if (dbHost) {
      console.log(chalk.dim(`   → Database: ${dbUser}@${dbHost}:${dbPort}/${dbName}`));
    }

    // Show schema stats
    const totalFields = config.schema.groups.reduce((sum, g) => sum + g.fields.length, 0);
    console.log(chalk.dim(`   → Schema: ${config.schema.groups.length} groups, ${totalFields} fields`));
  } else {
    warn('Cấu hình: Chưa thiết lập ❌ (chạy `taxsentry setup`)');
  }

  // 4. Service Status
  console.log();
  console.log(chalk.bold.cyan('Trạng thái dịch vụ:'));
  const botStatus = getServiceStatus('telegram_bot');
  if (botStatus.running) {
    success(`   Telegram Bot: Đang chạy (PID: ${botStatus.pid})`);
  } else {
    warn(`   Telegram Bot: Không đang chạy`);
  }

  // 5. Tips
  console.log();
  console.log(chalk.gray('─'.repeat(40)));
  console.log(chalk.dim('💡 Quản lý cấu hình linh hoạt:'));
  console.log(chalk.dim('  taxsentry config              → Xem config'));
  console.log(chalk.dim('  taxsentry config set <key> <v> → Sửa field'));
  console.log(chalk.dim('  taxsentry config add-field    → Thêm field mới'));
  console.log(chalk.dim('  taxsentry config rename-field → Đổi tên field'));
  console.log();
}
