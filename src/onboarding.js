/**
 * 🛡️ TaxSentry CLI - Onboarding Wizard
 * Interactive setup with Telegram Bot Token verification.
 */

import inquirer from 'inquirer';
import chalk from 'chalk';
import boxen from 'boxen';
import { getEmptyConfig, saveConfig, writeEnvFile, updateConfig } from './config.js';
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
 * Validate MySQL connection (basic check, can be extended).
 * For now, we just verify the format of the inputs.
 */
export function validateMySQL(config) {
  if (!config.mysql.port || isNaN(config.mysql.port) || config.mysql.port < 1 || config.mysql.port > 65535) {
    return 'Port phải là số từ 1 đến 65535.';
  }
  if (!config.mysql.host || config.mysql.host.trim() === '') {
    return 'Host không được để trống.';
  }
  return true;
}

/**
 * Main Onboarding Wizard.
 */
export async function runOnboarding() {
  console.log(
    boxen(
      chalk.bold.cyan(
        '🛡️ Bộ cài đặt cấu hình hệ thống TaxSentry (AI Co-pilot)\n\n' +
        'Chào mừng bạn đến với trình thiết lập cấu hình Onboarding.\n' +
        'Hệ thống sẽ lưu trữ bảo mật các tham số và tự động ghi nhận.'
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

  let config = getEmptyConfig();

  // 1. Director Name
  const { directorName } = await inquirer.prompt([
    {
      type: 'input',
      name: 'directorName',
      message: 'Tên Giám đốc / Người quản lý (dùng để hiển thị):',
      default: 'Giám đốc',
      validate: (input) => (input.trim().length > 2 ? true : 'Tên phải có ít nhất 3 ký tự.'),
    },
  ]);
  config.directorName = directorName.trim();

  // 2. Telegram Bot
  console.log(chalk.cyan('\n📱 Bước 1/4: Cấu hình Telegram Bot'));
  console.log(chalk.dim('   → Tạo bot mới tại @BotFather trên Telegram'));
  console.log(chalk.dim('   → Lấy "Bot Token" (định dạng: 123456789:ABCdefGHI...)\n'));

  let tokenValid = false;
  let botToken = '';
  let botInfo = null;

  while (!tokenValid) {
    const answers = await inquirer.prompt([
      {
        type: 'password',
        name: 'token',
        message: 'Nhập Telegram Bot Token:',
        validate: (input) => (input.match(/^\d+:.+/) ? true : 'Token phải bắt đầu bằng số và dấu hai chấm.'),
      },
    ]);
    botToken = answers.token;

    info('Đang xác thực Token với Telegram API...');
    const result = await verifyTelegramToken(botToken);
    
    if (result.valid) {
      tokenValid = true;
      botInfo = result;
      success(`Token hợp lệ! Bot: @${result.botName}`);
    } else {
      error(`Token không hợp lệ: ${result.error}`);
      const { retry } = await inquirer.prompt([
        { type: 'confirm', name: 'retry', message: 'Nhập lại Token?', default: true },
      ]);
      if (!retry) {
        console.log(chalk.yellow('\n👋 Thiết lập bị hủy.'));
        process.exit(0);
      }
    }
  }
  config.telegramBotToken = botToken;

  // 3. Admin Chat ID
  console.log(chalk.cyan('\n👤 Bước 2/4: Cấu hình Admin Chat ID'));
  console.log(chalk.dim(`   → Mở Telegram, tìm bot @${botInfo.botName}`));
  console.log(chalk.dim('   → Nhấn /start và gửi một tin nhắn bất kỳ'));
  console.log(chalk.dim('   → (Hoặc tự nhập nếu bạn đã có ID)\n'));

  const { adminChatId } = await inquirer.prompt([
    {
      type: 'input',
      name: 'adminChatId',
      message: 'Nhập Chat ID của Giám đốc (số hoặc -số):',
      validate: (input) => (/^-?\d+$/.test(input.trim()) ? true : 'Chat ID phải là số nguyên.'),
    },
  ]);
  config.adminChatId = adminChatId.trim();

  // 4. MySQL Config
  console.log(chalk.cyan('\n🗄️ Bước 3/4: Cấu hình MySQL Database'));
  const mysqlAnswers = await inquirer.prompt([
    {
      type: 'input',
      name: 'host',
      message: 'MySQL Host:',
      default: 'localhost',
    },
    {
      type: 'number',
      name: 'port',
      message: 'MySQL Port:',
      default: 3306,
    },
    {
      type: 'input',
      name: 'user',
      message: 'MySQL User:',
      default: 'root',
    },
    {
      type: 'password',
      name: 'password',
      message: 'MySQL Password:',
      default: '',
    },
    {
      type: 'input',
      name: 'database',
      message: 'Tên Database:',
      default: 'tax_sentry',
    },
  ]);
  config.mysql = mysqlAnswers;

  // 5. Email App Password
  console.log(chalk.cyan('\n📧 Bước 4/4: Cấu hình Email Kế toán (IMAP)'));
  console.log(chalk.dim('   → Vào Cài đặt Gmail/Tài khoản → Ứng dụng & Mật khẩu ứng dụng'));
  console.log(chalk.dim('   → Tạo mật khẩu ứng dụng (App Password) mới\n'));

  const emailAnswers = await inquirer.prompt([
    {
      type: 'input',
      name: 'address',
      message: 'Địa chỉ email Kế toán trưởng (IMAP):',
      default: 'ketoan@company.com',
    },
    {
      type: 'password',
      name: 'appPassword',
      message: 'Gmail App Password (16 ký tự, không dấu cách):',
      validate: (input) => (input.replace(/\s/g, '').length === 16 ? true : 'App Password phải đủ 16 ký tự.'),
      filter: (input) => input.replace(/\s/g, ''), // Remove spaces automatically
    },
  ]);
  config.email = {
    ...config.email,
    address: emailAnswers.address.trim(),
    appPassword: emailAnswers.appPassword,
  };

  // Finalize
  config.isConfigured = true;
  saveConfig(config);
  writeEnvFile(config);

  console.log();
  success('Cấu hình đã được lưu thành công vào ~/.taxsentry! 🎉');
  success(`Python .env file cũng đã được generate tại core.`);
  console.log(chalk.cyan('\nBạn có thể chạy lệnh sau để khởi động hệ thống:'));
  console.log(chalk.bold.white('  taxsentry start'));
  console.log();
  
  return config;
}
