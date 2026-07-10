/**
 * Shared Python entrypoint definitions for TaxSentry CLI commands.
 * Keeps the Node layer thin and the Python module boundaries explicit.
 */

export const FOREGROUND_MODULE = 'taxsentry';
export const TELEGRAM_BOT_MODULE = 'taxsentry.bot.telegram_bot';

export function getForegroundArgs() {
  return ['-m', FOREGROUND_MODULE];
}

export function getTelegramBotArgs(adminChatId) {
  return ['-m', TELEGRAM_BOT_MODULE, String(adminChatId)];
}
