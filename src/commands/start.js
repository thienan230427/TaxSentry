/**
 * 🛡️ TaxSentry CLI - Start Command
 * Foreground runner for the TUI Dashboard and Automation loop.
 */

import chalk from 'chalk';
import { startForeground } from '../launcher.js';
import { getDirectorName } from '../config.js';
import { getServiceModuleArgs } from '../utils/service-manager.js';
import { info, success } from '../utils/logger.js';

/**
 * Run the TUI Dashboard and Automation in the foreground.
 */
export default async function startCommand(deps = {}) {
  const startForegroundFn = deps.startForegroundFn ?? startForeground;
  const getDirectorNameFn = deps.getDirectorNameFn ?? getDirectorName;
  const getServiceModuleArgsFn = deps.getServiceModuleArgsFn ?? getServiceModuleArgs;

  try {
    const directorName = getDirectorNameFn() || 'Giám đốc';
    info(`Khởi động TUI Dashboard cho: ${directorName}`);

    console.log(chalk.dim('\n💡 Nhấn Ctrl+C để thoát Dashboard an toàn.\n'));

    const args = getServiceModuleArgsFn('foreground');
    const exitCode = startForegroundFn(args);

    if (exitCode === 0) {
      success('Dashboard đã đóng an toàn.');
    } else {
      // Warning, not error, as Ctrl+C returns non-zero sometimes
      info(`Dashboard kết thúc với mã: ${exitCode}`);
    }
  } catch (err) {
    console.error(chalk.red(`\n❌ Lỗi khi chạy start: ${err.message}`));
    process.exit(1);
  }
}
