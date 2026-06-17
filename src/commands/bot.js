/**
 * 🛡️ TaxSentry CLI - Bot Command
 * Background runner for the Telegram Bot.
 */

import { startBackground, isRunning, getPid } from '../launcher.js';
import { loadConfig } from '../config.js';
import { info, warn, success, error } from '../utils/logger.js';
import chalk from 'chalk';

/**
 * Run the Telegram Bot in the background.
 */
export default async function botCommand() {
  try {
    const config = loadConfig();
    info(`Định cấu hình Bot cho: ${config.directorName}`);

    // Check if already running
    if (isRunning('telegram_bot')) {
      warn(`Bot Telegram đang chạy với PID: ${getPid('telegram_bot')}`);
      process.exit(0);
    }

    // Bot script path relative to Python working dir
    // In our src layout: src/taxsentry/bot/telegram_bot.py
    const args = ['-m', 'taxsentry.bot.telegram_bot', '--admin-chat-id', config.adminChatId];
    
    const pid = startBackground('telegram_bot', args);

    if (pid) {
      success('Bot Telegram đã được khởi chạy thành công ở chế độ nền! 🤖');
      console.log(chalk.cyan(`   PID: ${pid}`));
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
