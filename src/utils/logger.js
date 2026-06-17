/**
 * 🛡️ TaxSentry CLI - Logger Utilities
 * Beautiful terminal output with chalk + ora + boxen integration.
 */

import chalk from 'chalk';
import boxen from 'boxen';
import figlet from 'figlet';

// Prefix constants
const PREFIX = '🛡️ TaxSentry';
const SUCCESS_PREFIX = '✅';
const WARN_PREFIX = '⚠️';
const ERROR_PREFIX = '❌';
const INFO_PREFIX = 'ℹ️';

/**
 * Print the TaxSentry ASCII banner.
 */
export function printBanner() {
  console.log();
  console.log(
    chalk.cyan(
      figlet.textSync('TaxSentry', { horizontalLayout: 'fitted' })
    )
  );
  console.log(
    chalk.cyan.bold(
      boxen('On-premise AI Audit Agent 🛡️', {
        padding: 0.5,
        margin: { top: 0, bottom: 1 },
        borderColor: 'cyan',
        borderStyle: 'round',
      })
    )
  );
}

/**
 * Print a step/phase header.
 */
export function printStep(phase, description) {
  console.log();
  console.log(chalk.bold.blue(`${PREFIX} Phase ${phase}`));
  console.log(chalk.blue(`→ ${description}`));
  console.log();
}

/**
 * Log an informational message.
 */
export function info(message) {
  console.log(chalk.cyan(`${INFO_PREFIX} ${message}`));
}

/**
 * Log a success message.
 */
export function success(message) {
  console.log(chalk.green(`${SUCCESS_PREFIX} ${message}`));
}

/**
 * Log a warning message.
 */
export function warn(message) {
  console.log(chalk.yellow(`${WARN_PREFIX} ${message}`));
}

/**
 * Log an error message.
 */
export function error(message) {
  console.error(chalk.red(`${ERROR_PREFIX} ${message}`));
}

/**
 * Log a debug message (only shown in verbose mode).
 */
export function debug(message, verbose = false) {
  if (verbose) {
    console.log(chalk.gray(`🔍 [debug] ${message}`));
  }
}

/**
 * Print a section divider.
 */
export function divider() {
  console.log(chalk.gray('─'.repeat(60)));
}

/**
 * Print a boxed welcome message.
 */
export function welcomeBox(directorName = 'Giám đốc') {
  const msg = chalk.bold.cyan(
    `🛡️ Chào mừng ${directorName} đến với hệ thống TaxSentry Agent!\n` +
    `Hệ thống AI giám sát kinh doanh & thuế tự động, bảo mật.\n` +
    `📁 Config: ~/.taxsentry/config.json`
  );
  console.log(
    boxen(msg, {
      padding: 1,
      margin: { top: 1, bottom: 1 },
      borderColor: 'cyan',
      borderStyle: 'round',
      title: 'TaxSentry AI Agent',
      titleAlignment: 'center',
    })
  );
}
