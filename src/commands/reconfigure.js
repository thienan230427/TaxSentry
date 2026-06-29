/**
 * 🛡️ TaxSentry CLI - Reconfigure Command
 * Runs onboarding without forcing a full reset, so blank secret fields can be preserved intentionally.
 */

import chalk from 'chalk';
import { isConfigured } from '../config.js';
import { runOnboarding } from '../onboarding.js';
import { info, success, warn, error } from '../utils/logger.js';

export async function runReconfigure(deps = {}) {
  const isConfiguredFn = deps.isConfigured ?? isConfigured;
  const runOnboardingFn = deps.runOnboarding ?? runOnboarding;

  if (!isConfiguredFn()) {
    warn('Chưa thấy cấu hình hiện tại. Hãy chạy `taxsentry setup` cho lần thiết lập đầu tiên.');
    process.exit(1);
  }

  try {
    info('Đang mở luồng reconfigure (không ép reset toàn bộ secret)...');
    await runOnboardingFn({ resetExisting: false });
    success('Reconfigure hoàn tất.');
  } catch (err) {
    error(`Reconfigure thất bại: ${err.message}`);
    process.exit(1);
  }
}

export default async function reconfigureCommand(deps = {}) {
  console.log(chalk.dim('\n🛠️ Chế độ reconfigure: giữ nguyên logic hiện có, chỉ hỏi lại các trường cần chỉnh sửa.\n'));
  await runReconfigure(deps);
}
