/**
 * 🛡️ TaxSentry CLI - Setup Command
 * Orchestrates the full setup workflow: Python check + Install + Onboarding.
 */

import inquirer from 'inquirer';
import { detectPython, printDetectionResult, getInstallInstructions } from '../utils/python-detector.js';
import { runInstallation } from '../installer.js';
import { runOnboarding } from '../onboarding.js';
import { isConfigured } from '../config.js';
import { info, success, error, warn } from '../utils/logger.js';
import chalk from 'chalk';

/**
 * Run the full setup workflow.
 */
export async function runSetup() {
  if (isConfigured()) {
    const { overwrite } = await inquirer.prompt([
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
    // 1. Ensure Python is available
    info('Đang kiểm tra Python...');
    const pyResult = detectPython();
    printDetectionResult(pyResult);

    if (!pyResult.found) {
      console.log(chalk.yellow('\n' + getInstallInstructions().join('\n')));
      console.log(chalk.red('\n❌ Không thể tiếp tục nếu không có Python 3.10+.'));
      process.exit(1);
    }

    // 2. Install venv + dependencies
    await runInstallation(pyResult.command, true);

    // 3. Run onboarding wizard
    await runOnboarding();

    success('\n🎉 Thiết lập hoàn tất! Bạn có thể chạy `taxsentry start` ngay bây giờ.');
  } catch (err) {
    error(`\nThiết lập thất bại: ${err.message}`);
    process.exit(1);
  }
}
