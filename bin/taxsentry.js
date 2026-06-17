#!/usr/bin/env node

/**
 * 🛡️ TaxSentry CLI - Main Entry Point
 * The dispatcher for all TaxSentry commands.
 */

import { Command } from 'commander';
import chalk from 'chalk';
import { printBanner, info, success, error, warn } from '../src/utils/logger.js';
import { detectPython, printDetectionResult, getInstallInstructions } from '../src/utils/python-detector.js';
import { runInstallation } from '../src/installer.js';
import { runOnboarding } from '../src/onboarding.js';
import { isConfigured, loadConfig } from '../src/config.js';
import { getPlatformName } from '../src/utils/paths.js';

const program = new Command();

program
  .name('taxsentry')
  .description('On-premise AI Audit Agent — automated tax risk monitoring for CFOs & SMEs')
  .version('0.1.0');

/**
 * Helper: Ensure Python is available before proceeding.
 */
async function ensurePython() {
  const result = detectPython();
  printDetectionResult(result);

  if (!result.found) {
    console.log(chalk.yellow('\n' + getInstallInstructions().join('\n')));
    console.log(chalk.red('\n❌ Không thể tiếp tục nếu không có Python 3.10+.'));
    process.exit(1);
  }

  return result.command;
}

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

    if (isConfigured()) {
      const { overwrite } = await (await import('inquirer')).default.prompt([
        {
          type: 'confirm',
          name: 'overwrite',
          message: 'Đã tìm thấy cấu hình cũ. Bạn có muốn ghi đè và cấu hình lại không?',
          default: false,
        },
      ]);
      if (!overwrite) {
        info('Đã hủy thiết lập.');
        process.exit(0);
      }
    }

    try {
      const pythonCmd = await ensurePython();
      await runInstallation(pythonCmd, true); // Always reinstall on fresh setup
      await runOnboarding();
      success('Thiết lập hoàn tất! 🎉');
    } catch (err) {
      error(`Thiết lập thất bại: ${err.message}`);
      process.exit(1);
    }
  });

/**
 * COMMAND: start
 * Start the TaxSentry TUI Dashboard and automation.
 */
program
  .command('start')
  .description('Khởi chạy TUI Dashboard + Automation Loop')
  .action(async () => {
    printBanner();
    info(`Đang chạy trên: ${getPlatformName()}\n`);

    if (!isConfigured()) {
      warn('Chưa tìm thấy cấu hình. Vui lòng chạy `taxsentry setup` trước.\n');
      const { proceed } = await (await import('inquirer')).default.prompt([
        {
          type: 'confirm',
          name: 'proceed',
          message: 'Bạn có muốn chạy wizard cấu hình ngay bây giờ không?',
          default: true,
        },
      ]);
      if (proceed) {
        program.parse(['node', 'taxsentry', 'setup'], { from: 'user' });
        return;
      } else {
        process.exit(0);
      }
    }

    const pythonCmd = await ensurePython();
    const config = loadConfig();

    info(`Khởi động hệ thống cho Giám đốc: ${config.directorName}`);
    info(`Sử dụng Python từ: ${pythonCmd}`);
    
    // TODO: Implement actual Python spawning logic here
    // For Phase 2, we just show a success message
    success('✅ Môi trường đã sẵn sàng! (Tính năng spawn Python core sẽ được hoàn thiện trong Phase 3)');
    console.log(chalk.cyan('\n💡 Gợi ý: Để chạy thử Python core trực tiếp, hãy vào thư mục taxsentry-core và chạy:'));
    console.log(chalk.white('  cd taxsentry-core'));
    console.log(chalk.white('  .venv\\Scripts\\python.exe -m taxsentry\n'));
  });

/**
 * COMMAND: status
 * Show system status.
 */
program
  .command('status')
  .description('Kiểm tra trạng thái hệ thống (Python, Config, Version)')
  .action(() => {
    console.log(chalk.bold.cyan('\n🛡️ TaxSentry System Status\n'));
    
    const py = detectPython();
    printDetectionResult(py);
    
    if (isConfigured()) {
      success('Cấu hình: Đã được thiết lập ✅');
      const config = loadConfig();
      console.log(chalk.dim(`   → Director: ${config.directorName}`));
      console.log(chalk.dim(`   → Bot: @${config.telegramBotToken.split(':')[0]}...`));
      console.log(chalk.dim(`   → DB: ${config.mysql.user}@${config.mysql.host}:${config.mysql.port}`));
    } else {
      warn('Cấu hình: Chưa thiết lập ❌');
    }
    console.log();
  });

/**
 * COMMAND: help (default behavior if no args)
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
