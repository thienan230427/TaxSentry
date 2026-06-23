/**
 * 🛡️ TaxSentry CLI - Start Command
 * Foreground runner for the TUI Dashboard and Automation loop.
 */

import { startForeground } from '../launcher.js';
import { getDirectorName } from '../config.js';
import { info, warn, success } from '../utils/logger.js';
import chalk from 'chalk';

/**
 * Run the TUI Dashboard and Automation in the foreground.
 */
export default async function startCommand() {
  try {
    const directorName = getDirectorName() || 'Giám đốc';
    info(`Khởi động TUI Dashboard cho: ${directorName}`);
    
    console.log(chalk.dim('\n💡 Nhấn Ctrl+C để thoát Dashboard an toàn.\n'));

    // Call python -m taxsentry
    const args = ['-m', 'taxsentry'];
    const exitCode = startForeground(args);

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
