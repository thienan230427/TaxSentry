/**
 * 🛡️ TaxSentry CLI - Up Command (Gateway)
 * Chạy TUI Dashboard và Telegram Bot song song.
 * Dùng new flexible config (getValue).
 */
import { startForeground, startAttached, stopService, isRunning } from '../launcher.js';
import { loadConfig, getValue } from '../config.js';
import { info, success, warn, error } from '../utils/logger.js';
import chalk from 'chalk';
import { sleep } from '../utils/helpers.js';

/**
 * Run the full TaxSentry stack: Telegram Bot (bg) + TUI Dashboard (fg).
 */
export default async function upCommand() {
  // 1. Kiểm tra config
  const config = loadConfig();
  if (!config.isConfigured) {
    warn('Chưa tìm thấy cấu hình. Vui lòng chạy `taxsentry setup` trước.\n');
    process.exit(1);
  }

  const directorName = getValue(config, 'director', 'directorName');
  const botToken = getValue(config, 'telegram', 'telegramBotToken');
  const adminChatId = getValue(config, 'telegram', 'adminChatId');

  info(`Khởi động TaxSentry Gateway cho: ${directorName}`);
  console.log(chalk.dim('💡 Nhấn Ctrl+C để tắt toàn bộ hệ thống.\n'));

  // 2. Start Telegram Bot ở background (attached — tự động tắt theo terminal)
  let botChild = null;
  if (botToken && botToken !== 'YOUR_BOT_TOKEN_HERE') {
    if (isRunning('telegram_bot')) {
      warn('Bot Telegram đã đang chạy. Bỏ qua bước khởi động bot.');
    } else {
      info('Đang khởi chạy Telegram Bot ở chế độ nền... 🤖');
      const args = ['-m', 'taxsentry.bot.telegram_bot', '--admin-chat-id', adminChatId];
      botChild = startAttached('telegram_bot', args);
      if (botChild) {
        success(`Telegram Bot đã chạy nền (PID: ${botChild.pid})`);
        // Đợi bot online
        await sleep(2000);
      } else {
        warn('Không thể khởi chạy Telegram Bot. Tiếp tục với TUI Dashboard...');
      }
    }
  } else {
    warn('Chưa cấu hình Telegram Bot Token. Chỉ chạy TUI Dashboard.');
    console.log(chalk.dim('  → Chạy `taxsentry setup` để cấu hình đầy đủ.\n'));
  }

  // 3. Chạy TUI Dashboard ở foreground (blocking)
  info('Đang khởi chạy TUI Dashboard... 📊');
  console.log(chalk.dim('  → Telegram Bot đang lắng nghe song song ở nền.\n'));

  const args = ['-m', 'taxsentry'];
  const exitCode = startForeground(args);

  // 4. Khi TUI tắt → dọn dẹp bot
  console.log();
  if (botChild || isRunning('telegram_bot')) {
    info('Đang dừng Telegram Bot...');
    stopService('telegram_bot');

    // Force kill attached child if still alive
    if (botChild && botChild.exitCode === null) {
      try { botChild.kill('SIGTERM'); } catch {}
    }
  }

  if (exitCode === 0) {
    success('TaxSentry Gateway đã đóng an toàn. 👋');
  } else {
    info(`Gateway kết thúc với mã: ${exitCode}`);
  }
}
