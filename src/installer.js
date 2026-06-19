/**
 * 🛡️ TaxSentry CLI - Installer Engine
 * Creates virtual environment and pip installs dependencies.
 */

import { execSync } from 'child_process';
import { existsSync, rmSync, cpSync, readFileSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import ora from 'ora';
import chalk from 'chalk';
import { VENV_DIR, CORE_DIR, getPythonPath, getPipPath, ensureDirectories } from './utils/paths.js';
import { info, success, error, warn } from './utils/logger.js';

// Project root = two levels up from installer.js (src/installer.js → project root)
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = join(__dirname, '..');
const PROJECT_CORE_DIR = join(PROJECT_ROOT, 'taxsentry-core');

/**
 * Check if virtual environment already exists and is valid.
 */
export function isVenvInstalled() {
  return existsSync(getPythonPath()) && existsSync(getPipPath());
}

/**
 * Remove existing venv (if requested).
 */
export function cleanupVenv() {
  if (existsSync(VENV_DIR)) {
    rmSync(VENV_DIR, { recursive: true, force: true });
  }
}

/**
 * Create Python virtual environment.
 */
export async function createVenv(pythonCmd) {
  const spinner = ora(`Đang tạo môi trường ảo Python tại ${VENV_DIR}...`).start();
  try {
    execSync(`"${pythonCmd}" -m venv "${VENV_DIR}"`, {
      stdio: 'pipe',
      timeout: 60000,
    });
    
    if (!isVenvInstalled()) {
      throw new Error('Tạo venv thất bại: không tìm thấy Python hoặc pip trong môi trường ảo mới.');
    }
    
    spinner.succeed('Môi trường ảo Python được tạo thành công! 🐍');
  } catch (err) {
    spinner.fail(`Tạo môi trường ảo thất bại: ${err.message}`);
    throw err;
  }
}

/**
 * Install Python dependencies via pip.
 */
export async function installDependencies(pythonCmd) {
  const requirementsPath = join(CORE_DIR, 'requirements.txt');
  if (!existsSync(requirementsPath)) {
    throw new Error(`Không tìm thấy file requirements.txt tại ${requirementsPath}`);
  }

  const spinner = ora('Đang cài đặt dependencies Python (có thể mất vài phút)...').start();
  try {
    const pipCmd = getPipPath();
    const pipArgs = [
      'install',
      '--upgrade',
      'pip',
      'setuptools',
      'wheel',
      '&&',
      `"${pipCmd}"`,
      'install', '-r', `"${requirementsPath}"`,
    ].join(' ');

    // Windows command chaining might need cmd /c, but cross-platform requires different approach
    // Let's do it in two steps for safety
    
    // 1. Upgrade pip (must use python -m pip on pip 25+ to modify itself)
    execSync(`"${pythonCmd}" -m pip install --upgrade pip setuptools wheel`, {
      stdio: 'pipe',
      timeout: 120000,
    });

    // 2. Install requirements
    execSync(`"${pipCmd}" install -r "${requirementsPath}"`, {
      stdio: 'pipe',
      cwd: CORE_DIR,
      timeout: 300000, // 5 minutes for large packages like reportlab, pandas
    });

    spinner.succeed('Cài đặt Python dependencies thành công! 📦');
  } catch (err) {
    spinner.fail(`Cài đặt dependencies thất bại: ${err.message}`);
    console.log(chalk.dim('\nGợi ý: Kiểm tra kết nối mạng và đảm bảo Python tương thích.\n'));
    throw err;
  }
}

/**
 * Copy the taxsentry-core source code from the project to ~/.taxsentry/taxsentry-core/
 */
export async function copyCoreSource() {
  const spinner = ora('Đang copy mã nguồn taxsentry-core...').start();

  if (!existsSync(PROJECT_CORE_DIR)) {
    spinner.fail(`Không tìm thấy thư mục taxsentry-core tại ${PROJECT_CORE_DIR}`);
    throw new Error(`Thư mục taxsentry-core không tồn tại. Kiểm tra lại cấu trúc dự án.`);
  }

  try {
    // Preserve existing .env before overwriting
    let existingEnv = null;
    const envFile = join(CORE_DIR, '.env');
    if (existsSync(envFile)) {
      existingEnv = readFileSync(envFile, 'utf-8');
    }

    // Ensure target directory exists
    ensureDirectories();

    // Remove old copy if exists
    if (existsSync(CORE_DIR)) {
      rmSync(CORE_DIR, { recursive: true, force: true });
    }

    // Copy recursively
    cpSync(PROJECT_CORE_DIR, CORE_DIR, { recursive: true });

    // Restore .env so config is not overwritten
    if (existingEnv) {
      writeFileSync(envFile, existingEnv, 'utf-8');
    }

    spinner.succeed('Đã copy mã nguồn taxsentry-core thành công! 📁');
  } catch (err) {
    spinner.fail(`Copy mã nguồn thất bại: ${err.message}`);
    throw err;
  }
}

/**
 * Full installation flow.
 */
export async function runInstallation(pythonCmd, forceReinstall = false) {
  console.log();
  info('Bắt đầu quy trình cài đặt môi trường TaxSentry...');
  
  if (isVenvInstalled() && !forceReinstall) {
    warn('Đã tìm thấy môi trường ảo. Đang kiểm tra tính toàn vẹn...');
    try {
      // Try to run a quick pip check
      execSync(`"${getPipPath()}" check`, { stdio: 'pipe', timeout: 5000 });
      success('Môi trường ảo đã được cài đặt và hoạt động ổn định. ✅\n');
      return true;
    } catch {
      warn('Môi trường ảo hiện tại có vấn đề. Đang cài đặt lại...');
      cleanupVenv();
    }
  } else if (isVenvInstalled() && forceReinstall) {
    warn('Flag --force được kích hoạt. Đang xóa môi trường cũ...');
    cleanupVenv();
  }

  await createVenv(pythonCmd);
  await copyCoreSource();
  await installDependencies(pythonCmd);

  success('Cài đặt môi trường Python hoàn tất! 🎉\n');
  return true;
}
