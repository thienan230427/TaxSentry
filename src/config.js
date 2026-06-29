/**
 * 🛡️ TaxSentry CLI - Configuration Manager (Flexible v2)
 * Dynamic schema config — khách hàng có thể thêm/sửa/xóa field linh hoạt.
 * Không hardcode field names: tất cả đều dựa trên schema + envMapping.
 */

import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'fs';
import { parse as parseDotenv } from 'dotenv';
import { CONFIG_FILE, ENV_FILE, CORE_DIR, ensureDirectories } from './utils/paths.js';

/* ─── Default Schema ───
 * Groups chứa fields. Mỗi field có:
 *   key        → tên trong config (không đổi sau khi tạo)
 *   label      → tên hiển thị cho người dùng (có thể đổi)
 *   type       → string | password | number | boolean
 *   default    → giá trị mặc định
 *   required   → true/false
 *   secret     → true (ẩn khi hiển thị)
 */

const DEFAULT_SCHEMA = {
  groups: [
    {
      id: 'director',
      label: 'Giám đốc',
      fields: [
        { key: 'directorName', label: 'Tên Giám đốc', type: 'string', default: 'Giám đốc', required: true },
        { key: 'directorEmail', label: 'Email nhận báo cáo của Giám đốc', type: 'string', default: '' },
      ],
    },
    {
      id: 'telegram',
      label: 'Telegram Bot',
      fields: [
        { key: 'telegramBotToken', label: 'Bot Token', type: 'password', default: '', required: true, secret: true },
        { key: 'adminChatId', label: 'Admin Chat ID', type: 'string', default: '', required: true },
      ],
    },
    {
      id: 'mysql',
      label: 'MySQL Database',
      fields: [
        { key: 'host', label: 'Host', type: 'string', default: 'localhost' },
        { key: 'port', label: 'Port', type: 'number', default: 3306 },
        { key: 'user', label: 'User', type: 'string', default: 'root' },
        { key: 'password', label: 'Password', type: 'password', default: '', secret: true },
        { key: 'database', label: 'Database Name', type: 'string', default: 'tax_sentry' },
      ],
    },
    {
      id: 'email',
      label: 'Email Kế toán',
      fields: [
        { key: 'address', label: 'Email Address', type: 'string', default: '' },
        { key: 'appPassword', label: 'App Password', type: 'password', default: '', secret: true },
        { key: 'host', label: 'IMAP Host', type: 'string', default: 'imap.gmail.com' },
        { key: 'port', label: 'IMAP Port', type: 'number', default: 993 },
        { key: 'accountantEmail', label: 'Email Kế toán trưởng (người gửi báo cáo)', type: 'string', default: '', required: true },
        { key: 'allowedReportSenders', label: 'Danh sách email được phép gửi báo cáo (CSV, tùy chọn)', type: 'string', default: '' },
      ],
    },
    {
      id: 'ai',
      label: 'AI Engine',
      fields: [
        { key: 'authMode', label: 'Chế độ xác thực AI (lmstudio hoặc codex_oauth)', type: 'string', default: 'lmstudio', required: true },
        { key: 'baseUrl', label: 'AI Base URL', type: 'string', default: 'http://localhost:1234/v1', required: true },
        { key: 'apiKey', label: 'AI API Key (để trống nếu dùng Codex OAuth)', type: 'password', default: '', secret: true },
        { key: 'modelName', label: 'Tên model AI', type: 'string', default: 'google/gemma-4-e4b', required: true },
      ],
    },
  ],
};

/* ─── Default envMapping ───
 * Map từ "groupId.fieldKey" → TÊN_BIẾN_MÔI_TRƯỜNG
 * Khách hàng có thể thêm mapping mới linh hoạt.
 */
const DEFAULT_ENV_MAPPING = {
  'director.directorName': 'DIRECTOR_NAME',
  'director.directorEmail': 'DIRECTOR_EMAIL',
  'telegram.telegramBotToken': 'TELEGRAM_BOT_TOKEN',
  'telegram.adminChatId': 'ADMIN_CHAT_ID',
  'mysql.host': 'DB_HOST',
  'mysql.port': 'DB_PORT',
  'mysql.user': 'DB_USER',
  'mysql.password': 'DB_PASS',
  'mysql.database': 'DB_NAME',
  'email.address': 'EMAIL_USER',
  'email.appPassword': 'EMAIL_PASS',
  'email.host': 'EMAIL_HOST',
  'email.port': 'EMAIL_PORT',
  'email.accountantEmail': 'ACCOUNTANT_EMAIL',
  'email.allowedReportSenders': 'ALLOWED_REPORT_SENDERS',
  'ai.authMode': 'TAXSENTRY_AI_AUTH_MODE',
  'ai.baseUrl': 'LM_STUDIO_URL',
  'ai.apiKey': 'LM_STUDIO_API_KEY',
  'ai.modelName': 'LM_MODEL_NAME',
};

/* ─── Helper: lấy field descriptor từ schema ─── */
function getFieldDescriptor(schema, groupId, fieldKey) {
  const group = schema.groups.find(g => g.id === groupId);
  if (!group) return null;
  return group.fields.find(f => f.key === fieldKey) || null;
}

function mergeSchemaWithDefaults(schema) {
  const merged = JSON.parse(JSON.stringify(schema || { groups: [] }));
  if (!Array.isArray(merged.groups)) merged.groups = [];

  for (const defaultGroup of DEFAULT_SCHEMA.groups) {
    const existingGroup = merged.groups.find(g => g.id === defaultGroup.id);
    if (!existingGroup) {
      merged.groups.push(JSON.parse(JSON.stringify(defaultGroup)));
      continue;
    }
    if (!Array.isArray(existingGroup.fields)) existingGroup.fields = [];
    for (const defaultField of defaultGroup.fields) {
      if (!existingGroup.fields.find(f => f.key === defaultField.key)) {
        existingGroup.fields.push(JSON.parse(JSON.stringify(defaultField)));
      }
    }
  }

  return merged;
}

function loadEnvSnapshot() {
  if (!existsSync(ENV_FILE)) return {};
  try {
    return parseDotenv(readFileSync(ENV_FILE, 'utf-8'));
  } catch {
    return {};
  }
}

/* ─── Helper: lấy value từ config ─── */
function getValue(config, groupId, fieldKey) {
  if (!config.values) config.values = {};
  if (!config.values[groupId]) config.values[groupId] = {};
  const val = config.values[groupId][fieldKey];
  const desc = getFieldDescriptor(config.schema, groupId, fieldKey);

  if ((val === undefined || val === null) && desc?.secret) {
    const envVar = config.envMapping?.[`${groupId}.${fieldKey}`];
    if (envVar) {
      const envValue = loadEnvSnapshot()[envVar];
      if (envValue !== undefined && envValue !== null && envValue !== '') {
        return envValue;
      }
    }
  }

  // Nếu value undefined/null, lấy default từ schema
  if (val === undefined || val === null) {
    return desc ? desc.default : '';
  }
  return val;
}

function createPersistedConfig(config) {
  const persisted = JSON.parse(JSON.stringify(config));
  const groups = persisted.schema?.groups || [];

  for (const group of groups) {
    const values = persisted.values?.[group.id];
    if (!values || typeof values !== 'object') continue;

    for (const field of group.fields || []) {
      if (field.secret) delete values[field.key];
    }
  }

  return persisted;
}

/* ─── Helper: set value vào config ─── */
function setValue(config, groupId, fieldKey, value) {
  if (!config.values) config.values = {};
  // Guard: prevent writing "undefined" as a group or field key
  if (!groupId || groupId === 'undefined' || groupId === 'null') return;
  if (!fieldKey || fieldKey === 'undefined' || fieldKey === 'null') return;
  if (!config.values[groupId]) config.values[groupId] = {};

  // Coerce type based on schema
  const desc = getFieldDescriptor(config.schema, groupId, fieldKey);
  if (desc && desc.type === 'number') {
    config.values[groupId][fieldKey] = Number(value);
  } else {
    config.values[groupId][fieldKey] = value;
  }
}

/* ─── Helper: flat map all values keyed by "groupId.fieldKey" ─── */
function flattenValues(config) {
  const flat = {};
  if (!config.values) return flat;
  for (const [gid, fields] of Object.entries(config.values)) {
    for (const [key, val] of Object.entries(fields)) {
      flat[`${gid}.${key}`] = val;
    }
  }
  return flat;
}

/* ─── Helper: migrate old config (v0.1.0) to v0.2.0 ─── */
function migrateOldConfig(oldConfig) {
  const newConfig = getEmptyConfig();
  // Map old flat fields to new grouped values
  const fieldMap = {
    directorName: { group: 'director', key: 'directorName' },
    telegramBotToken: { group: 'telegram', key: 'telegramBotToken' },
    adminChatId: { group: 'telegram', key: 'adminChatId' },
  };
  for (const [oldKey, mapping] of Object.entries(fieldMap)) {
    if (oldConfig[oldKey] !== undefined) {
      setValue(newConfig, mapping.group, mapping.key, oldConfig[oldKey]);
    }
  }
  // MySQL
  if (oldConfig.mysql) {
    for (const [k, v] of Object.entries(oldConfig.mysql)) {
      setValue(newConfig, 'mysql', k, v);
    }
  }
  // Email
  if (oldConfig.email) {
    for (const [k, v] of Object.entries(oldConfig.email)) {
      setValue(newConfig, 'email', k, v);
    }
  }
  // Custom fields from old config that don't match schema? Keep them in legacyCustom
  newConfig.legacyCustom = {};
  for (const [k, v] of Object.entries(oldConfig)) {
    if (!['version', 'directorName', 'telegramBotToken', 'adminChatId', 'mysql', 'email', 'isConfigured', 'schema', 'envMapping', 'values'].includes(k)) {
      newConfig.legacyCustom[k] = v;
    }
  }
  return newConfig;
}

/* ─── Main Functions ─── */

/**
 * Get empty config template (v0.2.0 with dynamic schema).
 */
export function getEmptyConfig() {
  return {
    version: '0.2.0',
    isConfigured: false,
    // Schema: định nghĩa groups và fields (có thể modify)
    schema: JSON.parse(JSON.stringify(DEFAULT_SCHEMA)),
    // envMapping: "groupId.fieldKey" → "ENV_VAR_NAME"
    envMapping: { ...DEFAULT_ENV_MAPPING },
    // values: { groupId: { fieldKey: value, ... }, ... }
    values: {},
    // Extra custom env vars — hoàn toàn trống, người dùng tự thêm qua CLI
    extraEnv: {},
  };
}

/**
 * Load configuration from JSON file.
 * Tự động migrate từ v0.1.0 lên v0.2.0 nếu cần.
 */
export function loadConfig() {
  ensureDirectories();
  if (!existsSync(CONFIG_FILE)) {
    return getEmptyConfig();
  }
  try {
    const data = readFileSync(CONFIG_FILE, 'utf-8');
    const parsed = JSON.parse(data);

    // Auto-migrate old config format (v0.1.x)
    if (parsed.version && parsed.version.startsWith('0.1.')) {
      const newConfig = migrateOldConfig(parsed);
      saveConfig(newConfig);
      return newConfig;
    }

    // Ensure new fields exist
    parsed.schema = mergeSchemaWithDefaults(parsed.schema || DEFAULT_SCHEMA);
    parsed.envMapping = { ...DEFAULT_ENV_MAPPING, ...(parsed.envMapping || {}) };
    if (!parsed.values) parsed.values = {};
    if (!parsed.extraEnv) parsed.extraEnv = {};

    // Fix: nếu values có key "undefined" (bug migration), unwrap nó
    for (const [gid, gval] of Object.entries(parsed.values)) {
      if (gval && typeof gval === 'object' && 'undefined' in gval) {
        parsed.values[gid] = gval['undefined'];
      }
    }

    return parsed;
  } catch (e) {
    throw new Error(`Không thể đọc file cấu hình: ${e.message}`);
  }
}

/**
 * Save configuration to JSON file.
 */
export function saveConfig(config) {
  ensureDirectories();
  const persisted = createPersistedConfig(config);
  writeFileSync(CONFIG_FILE, JSON.stringify(persisted, null, 2), 'utf-8');
}

/**
 * Update specific fields in config (partial update).
 * updates format: { groupId.fieldKey: value, ... }
 * Hoặc: { groupId: { fieldKey: value } }
 */
export function updateConfig(updates) {
  const config = loadConfig();
  for (const [key, value] of Object.entries(updates)) {
    if (key.includes('.')) {
      const [groupId, fieldKey] = key.split('.');
      setValue(config, groupId, fieldKey, value);
    } else if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
      // Nested object: { mysql: { host: '...' } }
      for (const [fieldKey, fv] of Object.entries(value)) {
        setValue(config, key, fieldKey, fv);
      }
    }
  }
  saveConfig(config);
  return config;
}

/* ═══════════════════════════════════════════════
   SCHEMA MODIFICATION FUNCTIONS
   Cho phép khách hàng thay đổi cấu trúc config
   ═══════════════════════════════════════════════ */

/**
 * Add a new field to a group.
 */
export function addField(groupId, fieldDef) {
  const config = loadConfig();
  const group = config.schema.groups.find(g => g.id === groupId);
  if (!group) throw new Error(`Group '${groupId}' không tồn tại.`);
  if (group.fields.find(f => f.key === fieldDef.key)) {
    throw new Error(`Field '${fieldDef.key}' đã tồn tại trong group '${groupId}'.`);
  }
  group.fields.push({
    key: fieldDef.key,
    label: fieldDef.label || fieldDef.key,
    type: fieldDef.type || 'string',
    default: fieldDef.default ?? '',
    required: fieldDef.required || false,
    secret: fieldDef.secret || false,
  });
  // Nếu có envVar mapping, thêm vào envMapping
  if (fieldDef.envVar) {
    config.envMapping[`${groupId}.${fieldDef.key}`] = fieldDef.envVar;
  }
  saveConfig(config);
  return config;
}

/**
 * Rename a field (đổi cả key và label).
 */
export function renameField(groupId, oldKey, newKey, newLabel) {
  const config = loadConfig();
  const group = config.schema.groups.find(g => g.id === groupId);
  if (!group) throw new Error(`Group '${groupId}' không tồn tại.`);

  const field = group.fields.find(f => f.key === oldKey);
  if (!field) throw new Error(`Field '${oldKey}' không tồn tại trong group '${groupId}'.`);

  // Move value từ oldKey sang newKey
  if (oldKey !== newKey && config.values[groupId]) {
    if (config.values[groupId][oldKey] !== undefined) {
      config.values[groupId][newKey] = config.values[groupId][oldKey];
      delete config.values[groupId][oldKey];
    }
    field.key = newKey;
  }

  if (newLabel) field.label = newLabel;

  // Update envMapping key
  if (config.envMapping[`${groupId}.${oldKey}`]) {
    config.envMapping[`${groupId}.${newKey}`] = config.envMapping[`${groupId}.${oldKey}`];
    delete config.envMapping[`${groupId}.${oldKey}`];
  }

  saveConfig(config);
  return config;
}

/**
 * Remove a field from a group.
 */
export function removeField(groupId, fieldKey) {
  const config = loadConfig();
  const group = config.schema.groups.find(g => g.id === groupId);
  if (!group) throw new Error(`Group '${groupId}' không tồn tại.`);
  if (group.fields.length <= 1) throw new Error(`Group '${groupId}' phải có ít nhất 1 field.`);

  const idx = group.fields.findIndex(f => f.key === fieldKey);
  if (idx === -1) throw new Error(`Field '${fieldKey}' không tồn tại trong group '${groupId}'.`);

  group.fields.splice(idx, 1);
  // Clean up value
  if (config.values[groupId]) delete config.values[groupId][fieldKey];
  // Clean up envMapping
  delete config.envMapping[`${groupId}.${fieldKey}`];

  saveConfig(config);
  return config;
}

/**
 * Add a new group to schema.
 */
export function addGroup(groupId, label) {
  const config = loadConfig();
  if (config.schema.groups.find(g => g.id === groupId)) {
    throw new Error(`Group '${groupId}' đã tồn tại.`);
  }
  config.schema.groups.push({ id: groupId, label: label || groupId, fields: [] });
  if (!config.values[groupId]) config.values[groupId] = {};
  saveConfig(config);
  return config;
}

/**
 * Add/update env mapping.
 */
export function setEnvMapping(fieldPath, envVar) {
  const config = loadConfig();
  config.envMapping[fieldPath] = envVar;
  saveConfig(config);
  return config;
}

/* ═══════════════════════════════════════════════
   .ENV GENERATION
   ═══════════════════════════════════════════════ */

/**
 * Generate .env file content from config (dynamic, based on envMapping).
 * Secret fields được ghi vào .env để runtime Python đọc được, nhưng không persist trong config.json.
 */
export function generateEnvContent(config) {
  const lines = [
    '# TaxSentry Environment Configuration',
    '# Generated automatically by TaxSentry CLI.',
    '#',
    '# ⚠️ Secret fields (passwords, tokens) may appear below for local runtime use.',
    '#    TaxSentry no longer persists those secret values in config.json.',
    '',
  ];

  // Generate from envMapping
  for (const [fieldPath, envVar] of Object.entries(config.envMapping || {})) {
    const [groupId, fieldKey] = fieldPath.split('.');
    const val = getValue(config, groupId, fieldKey);
    lines.push(`${envVar}=${val ?? ''}`);
  }

  // Extra env vars
  if (config.extraEnv) {
    lines.push('');
    lines.push('# Custom Environment Variables');
    for (const [k, v] of Object.entries(config.extraEnv)) {
      lines.push(`${k}=${v}`);
    }
  }

  return lines.join('\n');
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
 * Kiểm tra TaxSentry đã được cấu hình đầy đủ chưa.
 * Check: có file config + .env + các required fields đã điền.
 */
export function isConfigured() {
  if (!existsSync(CONFIG_FILE) || !existsSync(ENV_FILE)) return false;

  try {
    const config = loadConfig();
    // Check required fields
    for (const group of config.schema.groups) {
      for (const field of group.fields) {
        if (field.required) {
          const val = getValue(config, group.id, field.key);
          if (!val || val === '' || val === 'YOUR_BOT_TOKEN_HERE') return false;
        }
      }
    }
    return true;
  } catch {
    return false;
  }
}

/**
 * Get a specific value from config (for direct access).
 */
export function getConfigValue(groupId, fieldKey) {
  const config = loadConfig();
  return getValue(config, groupId, fieldKey);
}

/**
 * Quick getter for commonly used values.
 */
export function getTelegramToken() {
  return getConfigValue('telegram', 'telegramBotToken');
}

export function getAdminChatId() {
  return getConfigValue('telegram', 'adminChatId');
}

export function getDirectorName() {
  return getConfigValue('director', 'directorName');
}

/* ─── Export helpers for backward compat ─── */
export { getValue, setValue, flattenValues, DEFAULT_SCHEMA, DEFAULT_ENV_MAPPING };
