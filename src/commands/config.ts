/**
 * 🛡️ TaxSentry CLI - Config Command
 * Quản lý cấu hình linh hoạt: xem, sửa, thêm field, rename field.
 * Dùng schema dynamic — không hardcode bất kỳ field name nào.
 */

import { loadConfig, saveConfig, writeEnvFile, addField, renameField, removeField, addGroup, setEnvMapping, getValue, setValue, flattenValues } from '../config.ts';
import { info, success, error, warn } from '../utils/logger.ts';
import chalk from 'chalk';

function maskExtraEnvValue(key, value) {
  if (/(token|pass|secret|key)/i.test(key)) return '••••••••';
  return value;
}

/**
 * Display full config as a formatted table.
 */
export function displayConfig() {
  const config = loadConfig();

  console.log(chalk.bold.hex('#38bdf8')('\n╔═══════════════════════════════════════════════╗'));
  console.log(chalk.bold.hex('#38bdf8')('║       🛡️  TAXSENTRY CONFIGURATION            ║'));
  console.log(chalk.bold.hex('#38bdf8')('╚═══════════════════════════════════════════════╝'));
  console.log(chalk.dim(`Version: ${config.version}\n`));

  for (const group of config.schema.groups) {
    console.log(chalk.bold.hex('#67e8f9')(`📁 ${group.label} [${group.id}]`));
    console.log(chalk.hex('#1d4ed8')('─'.repeat(50)));

    for (const field of group.fields) {
      const val = getValue(config, group.id, field.key);
      let displayVal;

      if (field.secret) {
        displayVal = val ? '••••••••' : '(trống)';
      } else {
        displayVal = val !== undefined && val !== '' && val !== null ? String(val) : '(trống)';
      }

      const required = field.required ? chalk.hex('#fb7185')(' *') : '';
      console.log(`  ${chalk.hex('#38bdf8')(field.label)}${required}`);
      console.log(`  ${chalk.dim(`    key: ${chalk.white(group.id)}.${chalk.white(field.key)}`)}`);
      console.log(`    → ${displayVal}`);

      // Show env mapping nếu có
      const envVar = config.envMapping[`${group.id}.${field.key}`];
      if (envVar) {
        const secretVal = field.secret && val ? '••••••••' : (val || '');
        console.log(chalk.dim(`    .env: ${envVar}=${secretVal}`));
      }
      console.log();
    }
  }

  // Extra env
  if (config.extraEnv && Object.keys(config.extraEnv).length > 0) {
    console.log(chalk.bold.hex('#67e8f9')('📎 Extra Environment Variables:'));
    for (const [k, v] of Object.entries(config.extraEnv)) {
      console.log(chalk.dim(`  ${k}=${maskExtraEnvValue(k, v)}`));
    }
    console.log();
  }

  // Available commands
  console.log(chalk.hex('#1d4ed8')('─'.repeat(50)));
  console.log(chalk.dim('📝 Các lệnh quản lý config:'));
  console.log(chalk.dim('  taxsentry config set <groupId.fieldKey> <value>'));
  console.log(chalk.dim('  taxsentry config add-field <groupId> <key> <label> [type] [envVar]'));
  console.log(chalk.dim('  taxsentry config rename-field <groupId> <oldKey> <newKey> [newLabel]'));
  console.log(chalk.dim('  taxsentry config remove-field <groupId> <key>'));
  console.log(chalk.dim('  taxsentry config add-group <id> <label>'));
  console.log(chalk.dim('  taxsentry config env-map <fieldPath> <envVar>'));
  console.log(chalk.dim('  taxsentry config generate-env'));
  console.log();
}

/**
 * Set a config value: taxsentry config set <fieldPath> <value>
 * fieldPath = groupId.fieldKey (e.g. mysql.port, telegram.telegramBotToken)
 */
export function setConfigValue(fieldPath, value) {
  if (!fieldPath || !fieldPath.includes('.')) {
    error('Sai cú pháp. Dùng: taxsentry config set <groupId.fieldKey> <value>');
    process.exit(1);
  }

  const [groupId, fieldKey] = fieldPath.split('.');
  const config = loadConfig();

  // Check if field exists
  const group = config.schema.groups.find(g => g.id === groupId);
  if (!group) {
    error(`Group '${groupId}' không tồn tại. Các group hiện có: ${config.schema.groups.map(g => g.id).join(', ')}`);
    process.exit(1);
  }

  const field = group.fields.find(f => f.key === fieldKey);
  if (!field) {
    error(`Field '${fieldKey}' không tồn tại trong group '${groupId}'.`);
    error(`Các field hiện có: ${group.fields.map(f => `${f.key} (${f.label})`).join(', ')}`);
    process.exit(1);
  }

  setValue(config, groupId, fieldKey, value);
  saveConfig(config);
  writeEnvFile(config);
  success(`Đã cập nhật ${chalk.cyan(fieldPath)} = ${field.secret ? '••••••••' : value}`);
}

/**
 * Add a new field to a group.
 * taxsentry config add-field <groupId> <key> <label> [type] [envVar]
 */
export function addConfigField(groupId, key, label, type, envVar) {
  try {
    const fieldDef = {
      key,
      label: label || key,
      type: type || 'string',
      default: '',
      required: false,
      secret: type === 'password',
    };
    if (envVar) fieldDef.envVar = envVar;

    const result = addField(groupId, fieldDef);
    writeEnvFile(result);
    success(`Đã thêm field '${key}' vào group '${groupId}'.`);
    if (envVar) {
      success(`   .env mapping: ${groupId}.${key} → ${envVar}`);
    }
  } catch (err) {
    error(`❌ ${err.message}`);
    process.exit(1);
  }
}

/**
 * Rename a field: taxsentry config rename-field <groupId> <oldKey> <newKey> [newLabel]
 */
export function renameConfigField(groupId, oldKey, newKey, newLabel) {
  try {
    const result = renameField(groupId, oldKey, newKey, newLabel);
    writeEnvFile(result);
    success(`Đã đổi tên field '${oldKey}' → '${newKey}' trong group '${groupId}'.`);
  } catch (err) {
    error(`❌ ${err.message}`);
    process.exit(1);
  }
}

/**
 * Remove a field: taxsentry config remove-field <groupId> <key>
 */
export function removeConfigField(groupId, key) {
  try {
    const result = removeField(groupId, key);
    writeEnvFile(result);
    success(`Đã xóa field '${key}' khỏi group '${groupId}'.`);
  } catch (err) {
    error(`❌ ${err.message}`);
    process.exit(1);
  }
}

/**
 * Add a new group: taxsentry config add-group <id> <label>
 */
export function addConfigGroup(groupId, label) {
  try {
    addGroup(groupId, label);
    success(`Đã thêm group '${groupId}' (${label || groupId}).`);
    info('   Thêm field bằng: taxsentry config add-field ' + groupId + ' <key> <label>');
  } catch (err) {
    error(`❌ ${err.message}`);
    process.exit(1);
  }
}

/**
 * Set env mapping: taxsentry config env-map <fieldPath> <envVar>
 */
export function setEnvMappingCommand(fieldPath, envVar) {
  try {
    const result = setEnvMapping(fieldPath, envVar);
    writeEnvFile(result);
    success(`Đã set env mapping: ${fieldPath} → ${envVar}`);
  } catch (err) {
    error(`❌ ${err.message}`);
    process.exit(1);
  }
}

/**
 * Regenerate .env from config
 */
export function generateEnvCommand() {
  const config = loadConfig();
  writeEnvFile(config);
  success('Đã tạo lại file .env từ cấu hình hiện tại.');
}

