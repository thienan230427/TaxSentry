/**
 * 🛡️ TaxSentry CLI - Onboarding Wizard (Flexible Config v2)
 * Interactive setup với dynamic schema — dùng schema từ config để hỏi user.
 */

import inquirer from 'inquirer';
import chalk from 'chalk';
import boxen from 'boxen';
import { loadConfig, saveConfig, writeEnvFile, updateConfig, setValue, getValue, getEmptyConfig } from './config.js';
import { info, success, error, warn, divider } from './utils/logger.js';

/**
 * Verify if a Telegram Bot Token is valid by calling Telegram API.
 */
export async function verifyTelegramToken(token) {
  try {
    const response = await fetch(`https://api.telegram.org/bot${token}/getMe`);
    const data = await response.json();
    if (data.ok) {
      return { valid: true, botName: data.result.username, botId: data.result.id };
    }
    return { valid: false, error: data.description || 'Token không hợp lệ' };
  } catch (err) {
    return { valid: false, error: 'Không thể kết nối đến Telegram API. Kiểm tra mạng.' };
  }
}

/**
 * Validate MySQL connection (basic format check).
 */
export function validateMySQL(config) {
  const port = getValue(config, 'mysql', 'port');
  if (isNaN(port) || port < 1 || port > 65535) {
    return 'Port phải là số từ 1 đến 65535.';
  }
  return true;
}

/**
 * Run the onboarding wizard using the dynamic schema.
 */
export async function runOnboarding(options = {}) {
  console.log(
    boxen(
      chalk.bold.cyan(
        '🛡️ Bộ cài đặt cấu hình hệ thống TaxSentry (AI Co-pilot)\n\n' +
        'Chào mừng bạn đến với trình thiết lập cấu hình Onboarding.\n' +
        'Hệ thống sẽ lưu trữ bảo mật các tham số và tự động ghi nhận.\n' +
        'Bạn có thể thêm/sửa field sau bằng lệnh: taxsentry config'
      ),
      {
        padding: 1,
        margin: { top: 1, bottom: 1 },
        borderColor: 'cyan',
        borderStyle: 'round',
        title: 'TaxSentry Setup',
        titleAlignment: 'center',
      }
    )
  );

  divider();
  console.log(chalk.bold.red('⚠️ CHÍNH SÁCH BẢO MẬT & ĐIỀU KHOẢN SỬ DỤNG:'));
  console.log(chalk.yellow('1. Toàn bộ dữ liệu (API key, DB pass, App Password) được lưu cục bộ.'));
  console.log(chalk.yellow('2. Hệ thống AI xử lý cục bộ hoặc qua dịch vụ được chỉ định rõ ràng.'));
  console.log(chalk.yellow('3. Bạn chịu trách nhiệm bảo vệ file ~/.taxsentry/config.json.'));
  console.log(chalk.yellow('4. Bạn có thể thêm/sửa field bất kỳ lúc nào: taxsentry config add-field'));
  divider();

  const { agreed } = await inquirer.prompt([
    {
      type: 'confirm',
      name: 'agreed',
      message: 'Bạn có đồng ý với các điều khoản bảo mật dữ liệu trên không?',
      default: false,
    },
  ]);

  if (!agreed) {
    console.log(chalk.yellow('\n👋 Bạn chưa đồng ý điều khoản. Thiết lập bị hủy.'));
    process.exit(0);
  }

  console.log(chalk.green('\n✅ Bắt đầu thiết lập cấu hình...\n'));

  let config = options.resetExisting ? getEmptyConfig() : loadConfig();
  // Start fresh values if not already configured
  if (options.resetExisting || !config.isConfigured) {
    config.values = {};
  }

  // Walk through each group in schema
  for (const group of config.schema.groups) {
    console.log(chalk.cyan(`\n📋 Cấu hình: ${group.label}`));
    console.log(chalk.dim(`   (Group: ${group.id})`));

    const prompts = [];

    for (const field of group.fields) {
      const currentVal = getValue(config, group.id, field.key);
      const defaultVal = currentVal || field.default || '';

      const promptConfig = {
        type: field.type === 'password' ? 'password' : 'input',
        name: `${group.id}.${field.key}`,
        message: `${field.label}:`,
        default: field.type === 'password' ? '' : defaultVal,
      };

      // Validation cho required fields
      if (field.required) {
        promptConfig.validate = (input) => {
          if (!input || input.trim() === '') return `${field.label} không được để trống.`;
          // Special validation for Telegram Bot Token
          if (field.key === 'telegramBotToken') {
            return input.match(/^\d+:.+/) ? true : 'Token phải bắt đầu bằng số và dấu hai chấm.';
          }
          // Validation for Admin Chat ID
          if (field.key === 'adminChatId') {
            return /^-?\d+$/.test(input.trim()) ? true : 'Chat ID phải là số nguyên.';
          }
          return true;
        };
      }

      prompts.push(promptConfig);
    }

    if (prompts.length > 0) {
      const answers = await inquirer.prompt(prompts);

      // Save answers
      for (const [fullKey, value] of Object.entries(answers)) {
        const [gid, fk] = fullKey.split('.');
        const fieldDef = config.schema.groups
          .find((group) => group.id === gid)
          ?.fields.find((candidate) => candidate.key === fk);
        const shouldPreserveExistingSecret =
          fieldDef?.type === 'password' && value === '' && !options.resetExisting && getValue(config, gid, fk);

        if (shouldPreserveExistingSecret) {
          // Keep existing secret when user leaves password blank in reconfigure mode.
        } else {
          setValue(config, gid, fk, value);
        }
      }
    }
  }

  // Special: verify Telegram token
  const tgToken = getValue(config, 'telegram', 'telegramBotToken');
  if (tgToken && tgToken !== 'YOUR_BOT_TOKEN_HERE') {
    info('Đang xác thực Telegram Token với API...');
    const result = await verifyTelegramToken(tgToken);
    if (result.valid) {
      success(`Token hợp lệ! Bot: @${result.botName}`);
    } else {
      warn(`Không thể xác thực Token: ${result.error}`);
      warn('Bạn vẫn có thể tiếp tục và sửa sau: taxsentry config set telegram.telegramBotToken');
    }
  }

  // Finalize
  config.isConfigured = true;
  saveConfig(config);
  writeEnvFile(config);

  console.log();
  success('Cấu hình đã được lưu thành công vào ~/.taxsentry! 🎉');
  success(`Python .env file cũng đã được generate tại core.`);

  // Show summary
  console.log(chalk.cyan('\n📊 Tổng kết cấu hình:'));
  for (const group of config.schema.groups) {
    console.log(chalk.bold(`  ${group.label}:`));
    for (const field of group.fields) {
      const val = getValue(config, group.id, field.key);
      const displayVal = field.secret ? '••••••••' : (val || '(trống)');
      console.log(chalk.dim(`    ${field.label}: ${displayVal}`));
    }
  }

  console.log(chalk.cyan('\n💡 Các lệnh hữu ích:'));
  console.log(chalk.dim('  taxsentry config             → Xem toàn bộ config'));
  console.log(chalk.dim('  taxsentry config set <key> <value>  → Sửa 1 field'));
  console.log(chalk.dim('  taxsentry config add-field   → Thêm field mới'));
  console.log(chalk.dim('  taxsentry config rename-field → Đổi tên field'));
  console.log(chalk.dim('  taxsentry up                 → Chạy hệ thống'));
  console.log();

  return config;
}
