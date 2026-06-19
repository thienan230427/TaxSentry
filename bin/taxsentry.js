#!/usr/bin/env node

/**
 * 🛡️ TaxSentry CLI - Main Entry Point
 * The dispatcher for all TaxSentry commands.
 * Hỗ trợ flexible config: thêm/sửa/xóa field linh hoạt.
 */

import { Command } from 'commander';
import chalk from 'chalk';
import { printBanner, info, warn, error } from '../src/utils/logger.js';
import { isConfigured } from '../src/config.js';
import { getPlatformName } from '../src/utils/paths.js';

// Import command handlers
import startCommand from '../src/commands/start.js';
import botCommand from '../src/commands/bot.js';
import stopCommand from '../src/commands/stop.js';
import statusCommand from '../src/commands/status.js';
import upCommand from '../src/commands/up.js';
import { installServiceCommand, applyServiceCommand, removeServiceCommand, showServiceLogsCommand, showServiceStatus, uninstallServiceCommand } from '../src/commands/service.js';
import {
  displayConfig,
  setConfigValue,
  addConfigField,
  renameConfigField,
  removeConfigField,
  addConfigGroup,
  setEnvMappingCommand,
  generateEnvCommand,
} from '../src/commands/config.js';
import { detectPython, printDetectionResult, getInstallInstructions } from '../src/utils/python-detector.js';
import { runSetup } from '../src/commands/setup.js';

// SIGINT handler
process.on('SIGINT', () => {
  setTimeout(() => {
    process.exit(130);
  }, 3000).unref();
});

const program = new Command();

program
  .name('taxsentry')
  .description('On-premise AI Audit Agent — automated tax risk monitoring for CFOs & SMEs')
  .version('0.2.0')
  .addHelpText('afterAll', `
📖 HƯỚNG DẪN SỬ DỤNG NHANH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 LẦN ĐẦU TIÊN (cài đặt + cấu hình):
  taxsentry setup        → Kiểm tra Python → tạo venv → cài deps → wizard config

🚀 CHẠY HỆ THỐNG:
  taxsentry up           → Gateway: TUI Dashboard + Telegram Bot (song song)
                           💡 Bot tự động tắt khi đóng terminal
  taxsentry start        → Chỉ chạy TUI Dashboard (foreground)
  taxsentry bot          → Chỉ chạy Telegram Bot (background, sống độc lập)

🛑 DỪNG HỆ THỐNG:
  taxsentry stop         → Dừng bot nền (nếu chạy bằng "taxsentry bot")
  Ctrl+C                 → Thoát TUI + tự động dừng bot (nếu chạy bằng "taxsentry up")

🧩 SERVICE ARTIFACTS:
  taxsentry service status     → Xem định nghĩa service đa nền tảng hiện tại
  taxsentry service install    → Tạo file systemd / launchd / Task Scheduler
  taxsentry service apply      → Đăng ký service vào OS thật
  taxsentry service remove     → Gỡ service khỏi OS thật
  taxsentry service logs       → Xem log runtime nhanh
  taxsentry service uninstall  → Xóa file service đã sinh

⚙️ QUẢN LÝ CẤU HÌNH LINH HOẠT (không hardcode):
  taxsentry config                        → Xem toàn bộ cấu hình
  taxsentry config set <key> <value>       → Sửa 1 field (vd: mysql.port 3307)
  taxsentry config add-field <g> <k> <l>   → Thêm field mới
  taxsentry config rename-field <g> <k> <n>→ Đổi tên field
  taxsentry config remove-field <g> <k>    → Xóa field
  taxsentry config add-group <id> <label>  → Thêm group mới
  taxsentry config env-map <path> <var>    → Map field → biến .env
  taxsentry config generate-env            → Tạo lại .env

📋 KIỂM TRA:
  taxsentry status       → Xem trạng thái: Python, Config, Services

📌 LƯU Ý:
  • Tất cả dữ liệu cấu hình được lưu tại ~/.taxsentry/
  • Bot Telegram hỗ trợ các lệnh: /start, /reports, /analyze, /audit_history, /report_pdf
  • Môi trường Python ảo được tạo tại ~/.taxsentry/.venv/
  • Cấu hình linh hoạt: thêm/sửa field mà không cần edit code!

📦 YÊU CẦU:
  • Node.js >= 18
  • Python >= 3.10
  • MySQL (cho database)
  • Telegram Bot Token (từ @BotFather)
`);

/* ═══════════════════════════════════════════════
   COMMAND: config — QUẢN LÝ CẤU HÌNH LINH HOẠT
   ═══════════════════════════════════════════════ */
const configCommand = program
  .command('config')
  .description('Quản lý cấu hình linh hoạt (xem, sửa, thêm, xóa field)');

configCommand
  .command('show')
  .alias('list')
  .description('Hiển thị toàn bộ cấu hình hiện tại')
  .action(() => {
    printBanner();
    displayConfig();
  });

configCommand
  .command('set')
  .description('Sửa giá trị 1 field. VD: taxsentry config set mysql.port 3307')
  .argument('<fieldPath>', 'Đường dẫn field (vd: mysql.port, telegram.telegramBotToken)')
  .argument('<value>', 'Giá trị mới')
  .action((fieldPath, value) => {
    setConfigValue(fieldPath, value);
  });

configCommand
  .command('add-field')
  .description('Thêm field mới vào group. VD: taxsentry config add-field mysql sslMode "SSL Mode" boolean SSL_MODE')
  .argument('<groupId>', 'Tên group (vd: mysql, telegram)')
  .argument('<key>', 'Key của field (vd: sslMode)')
  .argument('<label>', 'Label hiển thị (vd: "SSL Mode")')
  .argument('[type]', 'Kiểu dữ liệu: string|password|number|boolean', 'string')
  .argument('[envVar]', 'Tên biến môi trường .env (VD: SSL_MODE)')
  .action((groupId, key, label, type, envVar) => {
    addConfigField(groupId, key, label, type, envVar);
  });

configCommand
  .command('rename-field')
  .description('Đổi tên field. VD: taxsentry config rename-field mysql host dbHost "Database Host"')
  .argument('<groupId>', 'Tên group')
  .argument('<oldKey>', 'Key cũ')
  .argument('<newKey>', 'Key mới')
  .argument('[newLabel]', 'Label mới (optional)')
  .action((groupId, oldKey, newKey, newLabel) => {
    renameConfigField(groupId, oldKey, newKey, newLabel);
  });

configCommand
  .command('remove-field')
  .description('Xóa field khỏi group. VD: taxsentry config remove-field mysql sslMode')
  .argument('<groupId>', 'Tên group')
  .argument('<key>', 'Key cần xóa')
  .action((groupId, key) => {
    removeConfigField(groupId, key);
  });

configCommand
  .command('add-group')
  .description('Thêm group mới. VD: taxsentry config add-group api "API Settings"')
  .argument('<id>', 'ID của group (vd: api)')
  .argument('<label>', 'Label hiển thị (vd: "API Settings")')
  .action((id, label) => {
    addConfigGroup(id, label);
  });

configCommand
  .command('env-map')
  .description('Map field → biến môi trường .env. VD: taxsentry config env-map mysql.sslMode SSL_MODE')
  .argument('<fieldPath>', 'Đường dẫn field (vd: mysql.sslMode)')
  .argument('<envVar>', 'Tên biến môi trường (vd: SSL_MODE)')
  .action((fieldPath, envVar) => {
    setEnvMappingCommand(fieldPath, envVar);
  });

configCommand
  .command('generate-env')
  .description('Tạo lại file .env từ cấu hình hiện tại')
  .action(() => {
    generateEnvCommand();
  });

// Default: show config
configCommand.action(() => {
  printBanner();
  displayConfig();
});

/* ═══════════════════════════════════════════════
   COMMAND: up
   ═══════════════════════════════════════════════ */
program
  .command('up')
  .description('Gateway: chạy TUI Dashboard + Telegram Bot song song')
  .action(async () => {
    printBanner();
    info(`Đang chạy trên: ${getPlatformName()}\n`);
    await upCommand();
  });

/* ═══════════════════════════════════════════════
   COMMAND: setup
   ═══════════════════════════════════════════════ */
program
  .command('setup')
  .description('Chạy wizard cấu hình ban đầu (Onboarding)')
  .action(async () => {
    printBanner();
    info(`Đang chạy trên: ${getPlatformName()}\n`);
    await runSetup();
  });

/* ═══════════════════════════════════════════════
   COMMAND: start
   ═══════════════════════════════════════════════ */
program
  .command('start')
  .description('Khởi chạy TUI Dashboard + Automation Loop (Foreground)')
  .action(async () => {
    if (!isConfigured()) {
      warn('Chưa tìm thấy cấu hình. Vui lòng chạy `taxsentry setup` trước.\n');
      process.exit(1);
    }
    printBanner();
    info(`Đang chạy trên: ${getPlatformName()}\n`);
    await startCommand();
  });

/* ═══════════════════════════════════════════════
   COMMAND: bot
   ═══════════════════════════════════════════════ */
program
  .command('bot')
  .description('Khởi chạy Telegram Bot ở chế độ nền (Background)')
  .action(async () => {
    if (!isConfigured()) {
      warn('Chưa tìm thấy cấu hình. Vui lòng chạy `taxsentry setup` trước.\n');
      process.exit(1);
    }
    printBanner();
    info(`Đang khởi chạy Bot ở chế độ nền...\n`);
    await botCommand();
  });

/* ═══════════════════════════════════════════════
   COMMAND: stop
   ═══════════════════════════════════════════════ */
program
  .command('stop')
  .description('Dừng tất cả các dịch vụ nền đang chạy')
  .action(async () => {
    printBanner();
    info(`Đang dừng các dịch vụ nền...\n`);
    await stopCommand();
  });

/* ═══════════════════════════════════════════════
   COMMAND: status
   ═══════════════════════════════════════════════ */
program
  .command('status')
  .description('Kiểm tra trạng thái hệ thống (Python, Config, Services)')
  .action(async () => {
    printBanner();
    await statusCommand();
  });

/* ═══════════════════════════════════════════════
   COMMAND: service
   ═══════════════════════════════════════════════ */
const serviceCommand = program
  .command('service')
  .description('Sinh/gỡ định nghĩa service đa nền tảng cho Telegram Bot');

serviceCommand
  .command('status')
  .description('Xem trạng thái artifact service hiện tại')
  .option('--service <name>', 'Tên service cần thao tác', 'telegram_bot')
  .action((options) => {
    printBanner();
    showServiceStatus(options.service);
  });

serviceCommand
  .command('install')
  .description('Sinh file service cho systemd / launchd / Task Scheduler')
  .option('--service <name>', 'Tên service cần thao tác', 'telegram_bot')
  .action((options) => {
    printBanner();
    installServiceCommand(options.service);
  });

serviceCommand
  .command('apply')
  .description('Đăng ký service vào OS thật (Task Scheduler / systemd / launchd)')
  .option('--service <name>', 'Tên service cần thao tác', 'telegram_bot')
  .action((options) => {
    printBanner();
    applyServiceCommand(options.service);
  });

serviceCommand
  .command('remove')
  .description('Gỡ service khỏi OS thật')
  .option('--service <name>', 'Tên service cần thao tác', 'telegram_bot')
  .option('--purge-artifacts', 'Xóa luôn artifact local sau khi remove khỏi OS', false)
  .action((options) => {
    printBanner();
    removeServiceCommand(options.service, options.purgeArtifacts);
  });

serviceCommand
  .command('logs')
  .description('Xem log runtime gần nhất của service')
  .option('--service <name>', 'Tên service cần thao tác', 'telegram_bot')
  .option('--lines <n>', 'Số dòng log muốn xem', '40')
  .action((options) => {
    printBanner();
    showServiceLogsCommand(options.service, Number(options.lines || 40));
  });

serviceCommand
  .command('uninstall')
  .description('Xóa file service đã sinh')
  .option('--service <name>', 'Tên service cần thao tác', 'telegram_bot')
  .action((options) => {
    printBanner();
    uninstallServiceCommand(options.service);
  });

serviceCommand.action(() => {
  printBanner();
  showServiceStatus('telegram_bot');
});

/* ═══════════════════════════════════════════════
   DEFAULT
   ═══════════════════════════════════════════════ */
program.action(() => {
  printBanner();
  program.help();
});

// Parse arguments
program.parse(process.argv);

// If no arguments provided, show help
if (process.argv.length === 2) {
  program.help();
}
