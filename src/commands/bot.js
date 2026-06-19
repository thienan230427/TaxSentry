/**
 * 🛡️ TaxSentry CLI - Bot Command
 * Background runner for the Telegram Bot.
 * Dùng new flexible config (getValue).
 */
import { startBackground, isRunning, getPid } from '../launcher.js';
import { loadConfig, getValue } from '../config.js';
import { getServiceAdapter } from '../utils/service-manager.js';
import { info, warn, success, error } from '../utils/logger.js';
import chalk from 'chalk';

/**
 * Run the Telegram Bot in the background.
 */
export default async function botCommand() {
  try {
    const config = loadConfig();
    const directorName = getValue(config, 'director', 'directorName');
    const adminChatId = getValue(config, 'telegram', 'adminChatId');
    const botToken = getValue(config, 'telegram', 'telegramBotToken');

    info(`Định cấu hình Bot cho: ${directorName}`);

    // Check if already running
    if (isRunning('telegram_bot')) {
      warn(`Bot Telegram đang chạy với PID: ${getPid('telegram_bot')}`);
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

    // Bot script path relative to Python working dir
    const args = ['-m', 'taxsentry.bot.telegram_bot', '--admin-chat-id', adminChatId];
    const adapter = getServiceAdapter('telegram_bot');

    const pid = startBackground('telegram_bot', args);

    if (pid) {
      success('Bot Telegram đã được khởi chạy thành công ở chế độ nền! 🤖');
      console.log(chalk.dim(`   PID: ${pid}`));
      console.log(chalk.dim(`   Adapter: ${adapter.runtimeMode}`));
      console.log(chalk.dim(`   Supervisor đề xuất: ${adapter.recommendedSupervisor}`));
      console.log(chalk.dim(`   Để xem log: taxsentry logs --service bot`));
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
