#!/usr/bin/env node

/**
 * 🛡️ TaxSentry CLI - Main Entry Point
 * The dispatcher for all TaxSentry commands.
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
import { detectPython, printDetectionResult, getInstallInstructions } from '../src/utils/python-detector.js';
import { runSetup } from '../src/commands/setup.js';

const program = new Command();

program
  .name('taxsentry')
  .description('On-premise AI Audit Agent — automated tax risk monitoring for CFOs & SMEs')
  .version('0.1.0');

/**
 * COMMAND: setup
 * Run the interactive onboarding wizard.
 */
program
  .command('setup')
  .description('Chạy wizard cấu hình ban đầu (Onboarding)')
  .action(async () => {
    printBanner();
    info(`Đang chạy trên: ${getPlatformName()}\n`);
    
    await runSetup();
  });

/**
 * COMMAND: start
 * Start the TaxSentry TUI Dashboard and automation.
 */
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

/**
 * COMMAND: bot
 * Start the Telegram Bot in the background.
 */
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

/**
 * COMMAND: stop
 * Stop all background services.
 */
program
  .command('stop')
  .description('Dừng tất cả các dịch vụ nền đang chạy')
  .action(async () => {
    printBanner();
    info(`Đang dừng các dịch vụ nền...\n`);
    
    await stopCommand();
  });

/**
 * COMMAND: status
 * Show system status.
 */
program
  .command('status')
  .description('Kiểm tra trạng thái hệ thống (Python, Config, Services)')
  .action(async () => {
    printBanner();
    await statusCommand();
  });

/**
 * Default action
 */
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
