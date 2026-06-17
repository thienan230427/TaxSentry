/**
 * 🛡️ TaxSentry CLI - Configuration Manager
 * Safe reading and writing of ~/.taxsentry/config.json and .env files.
 */

import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'fs';
import { CONFIG_FILE, ENV_FILE, CORE_DIR, ensureDirectories } from './utils/paths.js';

/**
 * Load configuration from JSON file.
 * Returns default empty config if not found.
 */
export function loadConfig() {
  ensureDirectories();
  if (!existsSync(CONFIG_FILE)) {
    return getEmptyConfig();
  }
  try {
    const data = readFileSync(CONFIG_FILE, 'utf-8');
    return JSON.parse(data);
  } catch (e) {
    throw new Error(`Không thể đọc file cấu hình: ${e.message}`);
  }
}

/**
 * Save configuration to JSON file.
 */
export function saveConfig(config) {
  ensureDirectories();
  writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2), 'utf-8');
}

/**
 * Get empty config template.
 */
export function getEmptyConfig() {
  return {
    version: '0.1.0',
    directorName: 'Giám đốc',
    telegramBotToken: '',
    adminChatId: '',
    mysql: {
      host: 'localhost',
      port: 3306,
      user: 'root',
      password: '',
      database: 'tax_sentry',
    },
    email: {
      address: '',
      appPassword: '',
      host: 'imap.gmail.com',
      port: 993,
    },
    isConfigured: false,
  };
}

/**
 * Update specific fields in config (partial update).
 */
export function updateConfig(updates) {
  const config = loadConfig();
  // Deep merge for nested objects
  const merged = mergeDeep(config, updates);
  saveConfig(merged);
  return merged;
}

/**
 * Simple deep merge utility.
 */
function mergeDeep(target, source) {
  const result = { ...target };
  for (const key in source) {
    if (
      source[key] instanceof Object &&
      key in target &&
      target[key] instanceof Object
    ) {
      result[key] = mergeDeep(target[key], source[key]);
    } else {
      result[key] = source[key];
    }
  }
  return result;
}

/**
 * Generate .env file content from config.
 */
export function generateEnvContent(config) {
  return `# TaxSentry Environment Configuration
# Generated automatically by TaxSentry CLI. Do not edit manually.

# Telegram Bot
TELEGRAM_BOT_TOKEN=${config.telegramBotToken}
ADMIN_CHAT_ID=${config.adminChatId}
DIRECTOR_NAME=${config.directorName}

# MySQL Database
DB_HOST=${config.mysql.host}
DB_PORT=${config.mysql.port}
DB_USER=${config.mysql.user}
DB_PASS=${config.mysql.password}
DB_NAME=${config.mysql.database}

# Email Configuration
EMAIL_ADDRESS=${config.email.address}
EMAIL_PASS=${config.email.appPassword}
IMAP_HOST=${config.email.host}
IMAP_PORT=${config.email.port}
`;
}

/**
 * Write .env file to Python core directory.
 */
export function writeEnvFile(config) {
  const content = generateEnvContent(config);
  mkdirSync(CORE_DIR, { recursive: true });
  writeFileSync(ENV_FILE, content, 'utf-8');
}

/**
 * Check if TaxSentry is fully configured.
 */
export function isConfigured() {
  return existsSync(CONFIG_FILE) && existsSync(ENV_FILE);
}
