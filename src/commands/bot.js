/**
 * 🛡️ TaxSentry CLI - Bot Command
 * Background runner for the Telegram Bot.
 * Dùng new flexible config (getValue).
 */
import chalk from 'chalk';
import { startBackground, isRunning, getPid } from '../launcher.js';
import { loadConfig, getValue } from '../config.js';
import { getServiceAdapter, getServiceModuleArgs } from '../utils/service-manager.js';
import { info, warn, success, error } from '../utils/logger.js';

/**
 * Run the Telegram Bot in the background.
 */
export default async function botCommand(deps = {}) {
  const loadConfigFn = deps.loadConfigFn ?? loadConfig;
  const getValueFn = deps.getValueFn ?? getValue;
  const startBackgroundFn = deps.startBackgroundFn ?? startBackground;
  const isRunningFn = deps.isRunningFn ?? isRunning;
  const getPidFn = deps.getPidFn ?? getPid;
  const getServiceAdapterFn = deps.getServiceAdapterFn ?? getServiceAdapter;
  const getServiceModuleArgsFn = deps.getServiceModuleArgsFn ?? getServiceModuleArgs;

  try {
    const config = loadConfigFn();
    const directorName = getValueFn(config, 'director', 'directorName');
    const adminChatId = getValueFn(config, 'telegram', 'adminChatId');
    const botToken = getValueFn(config, 'telegram', 'telegramBotToken');

    info(`Định cấu hình Bot cho: ${directorName}`);

    // Check if already running
    if (isRunningFn('telegram_bot')) {
      warn(`Bot Telegram đang chạy với PID: ${getPidFn('telegram_bot')}`);
      process.exit(0);
    }

    if (!botToken || botToken === 'YOUR_BOT_TOKEN_HERE') {
      error('Chưa cấu hình Telegram Bot Token. Chạy: taxsentry setup');
      process.exit(1);
    }

    if (!adminChatId) {
      error('Chưa cấu hình Admin Chat ID. Chạy: taxsentry setup');
      process.exit(1);
    }

    const args = getServiceModuleArgsFn('telegram_bot', adminChatId);
    const adapter = getServiceAdapterFn('telegram_bot');

    const pid = startBackgroundFn('telegram_bot', args);

    if (pid) {
      success('Bot Telegram đã được khởi chạy thành công ở chế độ nền! 🤖');
      console.log(chalk.dim(`   PID: ${pid}`));
      console.log(chalk.dim(`   Adapter: ${adapter.runtimeMode}`));
      console.log(chalk.dim(`   Supervisor đề xuất: ${adapter.recommendedSupervisor}`));
      console.log(chalk.dim(`   Để xem log: taxsentry logs --service telegram_bot`));
      console.log(chalk.dim(`   Để dừng bot: taxsentry stop`));
    } else {
      error('Không thể khởi chạy Bot Telegram.');
      process.exit(1);
    }
  } catch (err) {
    console.error(chalk.red(`\n❌ Lỗi khi chạy bot: ${err.message}`));
    process.exit(1);
  }
}
