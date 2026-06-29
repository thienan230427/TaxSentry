/**
 * 🛡️ TaxSentry CLI - Up Command (Gateway)
 * Chạy TUI Dashboard và Telegram Bot song song.
 * Dùng new flexible config (getValue).
 */
import chalk from 'chalk';
import { startForeground, startAttached, stopService, isRunning } from '../launcher.js';
import { loadConfig, getValue } from '../config.js';
import { getServiceModuleArgs } from '../utils/service-manager.js';
import { getTelegramBotArgs, getForegroundArgs } from '../runtime/entrypoints.js';
import { info, success, warn } from '../utils/logger.js';
import { sleep } from '../utils/helpers.js';

/**
 * Run the full TaxSentry stack: Telegram Bot (bg) + TUI Dashboard (fg).
 */
export default async function upCommand(deps = {}) {
  const loadConfigFn = deps.loadConfigFn ?? loadConfig;
  const getValueFn = deps.getValueFn ?? getValue;
  const startForegroundFn = deps.startForegroundFn ?? startForeground;
  const startAttachedFn = deps.startAttachedFn ?? startAttached;
  const stopServiceFn = deps.stopServiceFn ?? stopService;
  const isRunningFn = deps.isRunningFn ?? isRunning;
  const getServiceModuleArgsFn = deps.getServiceModuleArgsFn ?? getServiceModuleArgs;
  const sleepFn = deps.sleepFn ?? sleep;
  const getTelegramBotArgsFn = deps.getTelegramBotArgsFn ?? getTelegramBotArgs;
  const getForegroundArgsFn = deps.getForegroundArgsFn ?? getForegroundArgs;

  // 1. Kiểm tra config
  const config = loadConfigFn();
  if (!config.isConfigured) {
    warn('Chưa tìm thấy cấu hình. Vui lòng chạy `taxsentry setup` trước.\n');
    process.exit(1);
  }

  const directorName = getValueFn(config, 'director', 'directorName');
  const botToken = getValueFn(config, 'telegram', 'telegramBotToken');
  const adminChatId = getValueFn(config, 'telegram', 'adminChatId');

  info(`Khởi động TaxSentry Gateway cho: ${directorName}`);
  console.log(chalk.dim('💡 Nhấn Ctrl+C để tắt toàn bộ hệ thống.\n'));

  // 2. Start Telegram Bot ở background (attached — tự động tắt theo terminal)
  let botChild = null;
  if (botToken && botToken !== 'YOUR_BOT_TOKEN_HERE') {
    if (!adminChatId) {
      warn('Chưa cấu hình Admin Chat ID. Bỏ qua khởi động bot để tránh chạy lệch cấu hình.');
    } else if (isRunningFn('telegram_bot')) {
      warn('Bot Telegram đã đang chạy. Bỏ qua bước khởi động bot.');
    } else {
      info('Đang khởi chạy Telegram Bot ở chế độ nền... 🤖');
      const args = getServiceModuleArgsFn('telegram_bot', adminChatId);
      botChild = startAttachedFn('telegram_bot', args);

      if (botChild) {
        success(`Telegram Bot đã chạy nền (PID: ${botChild.pid})`);
        // Đợi bot online
        await sleepFn(2000);
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
  if (botChild || isRunningFn('telegram_bot')) {
    console.log(chalk.dim('  → Telegram Bot đang lắng nghe song song ở nền.\n'));
  } else {
    console.log(chalk.dim('  → Chỉ chạy TUI Dashboard độc lập.\n'));
  }

  const args = getForegroundArgsFn();
  const exitCode = startForegroundFn(args);

  // 4. Khi TUI tắt → dọn dẹp bot
  console.log();
  if (botChild || isRunningFn('telegram_bot')) {
    info('Đang dừng Telegram Bot...');
    stopServiceFn('telegram_bot');

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
