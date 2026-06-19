/**
 * 🛡️ TaxSentry CLI - Helper Utilities
 * Cross-cutting shared utilities.
 */

/**
 * Promise-based sleep.
 */
export function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Format a timestamp for display.
 */
export function formatTimestamp(date = new Date()) {
  return date.toLocaleString('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}
