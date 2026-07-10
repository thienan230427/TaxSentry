/**
 * 🛡️ TaxSentry CLI - Logger Utilities
 * Beautiful terminal output with chalk + ora + boxen integration.
 */

import chalk from 'chalk';
import figlet from 'figlet';

import { BLUE_THEME, oceanFrame } from './terminal-theme.ts';

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
    BLUE_THEME.primary(
      figlet.textSync('TaxSentry', { horizontalLayout: 'fitted' })
    )
  );
  console.log(oceanFrame('Blue terminal cockpit', ['On-premise AI audit agent', 'Local-first. Memory-aware. Terminal-native.'], { subtitle: 'A calmer, sharper blue workspace' }));
}

/**
 * Print a step/phase header.
 */
export function printStep(phase, description) {
  console.log();
  console.log(chalk.bold.hex('#38bdf8')(`${PREFIX} Phase ${phase}`));
  console.log(chalk.hex('#67e8f9')(`→ ${description}`));
  console.log();
}

/**
 * Log an informational message.
 */
export function info(message) {
  console.log(chalk.hex('#67e8f9')(`${INFO_PREFIX} ${message}`));
}

/**
 * Log a success message.
 */
export function success(message) {
  console.log(chalk.hex('#22d3ee')(`${SUCCESS_PREFIX} ${message}`));
}

/**
 * Log a warning message.
 */
export function warn(message) {
  console.log(chalk.hex('#93c5fd')(`${WARN_PREFIX} ${message}`));
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
  console.log(chalk.hex('#1d4ed8')('─'.repeat(60)));
}

/**
 * Print a boxed welcome message.
 */
export function welcomeBox(directorName = 'Giám đốc') {
  console.log(oceanFrame(
    `Chào mừng ${directorName} đến với TaxSentry`,
    [
      chalk.white('Hệ thống AI giám sát kinh doanh & thuế tự động, bảo mật.'),
      chalk.hex('#67e8f9')('📁 Config: ~/.taxsentry/config.json'),
    ],
    { subtitle: 'Blue cockpit mode' },
  ));
}
