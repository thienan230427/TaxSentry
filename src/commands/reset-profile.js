/**
 * 🛡️ TaxSentry CLI - Reset Profile Command
 * Fully resets the local profile and reruns onboarding from a clean slate.
 */

import inquirer from 'inquirer';
import chalk from 'chalk';
import { detectPython, printDetectionResult, getInstallInstructions } from '../utils/python-detector.js';
import { runInstallation } from '../installer.js';
import { runOnboarding } from '../onboarding.js';
import { isConfigured } from '../config.js';
import { info, success, error, warn } from '../utils/logger.js';

export async function runResetProfile(deps = {}) {
  const prompt = deps.prompt ?? inquirer.prompt.bind(inquirer);
  const isConfiguredFn = deps.isConfigured ?? isConfigured;
  const detectPythonFn = deps.detectPython ?? detectPython;
  const printDetectionResultFn = deps.printDetectionResult ?? printDetectionResult;
  const getInstallInstructionsFn = deps.getInstallInstructions ?? getInstallInstructions;
  const runInstallationFn = deps.runInstallation ?? runInstallation;
  const runOnboardingFn = deps.runOnboarding ?? runOnboarding;

  if (isConfiguredFn()) {
    const { confirmReset } = await prompt([
      {
        type: 'confirm',
        name: 'confirmReset',
        message: 'Thao tác này sẽ xóa profile hiện tại và thiết lập lại từ đầu. Tiếp tục chứ?',
        default: false,
      },
    ]);

    if (!confirmReset) {
      info('Đã hủy reset profile.');
      process.exit(0);
    }
  }

  try {
    info('Đang reset profile và cài lại từ trạng thái sạch...');
    const pyResult = detectPythonFn();
    printDetectionResultFn(pyResult);

    if (!pyResult.found) {
      console.log(chalk.yellow('\n' + getInstallInstructionsFn().join('\n')));
      console.log(chalk.red('\n❌ Không thể tiếp tục nếu không có Python 3.10+.'));
      process.exit(1);
    }

    await runInstallationFn(pyResult.command, true);
    await runOnboardingFn({ resetExisting: true });

    success('Reset profile hoàn tất. Bạn có thể chạy `taxsentry start` ngay bây giờ.');
  } catch (err) {
    error(`Reset profile thất bại: ${err.message}`);
    process.exit(1);
  }
}

export default async function resetProfileCommand(deps = {}) {
  console.log(chalk.dim('\n🧹 Chế độ reset profile: xóa profile cũ và chạy onboarding từ đầu.\n'));
  await runResetProfile(deps);
}
