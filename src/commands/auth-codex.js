/**
 * TaxSentry CLI - Codex OAuth auth command
 */

import chalk from 'chalk';
import { loadConfig, saveConfig, writeEnvFile, setValue, getValue } from '../config.js';
import { info, success, error } from '../utils/logger.js';
import { loadCodexAuth, redactCodexAuthSummary } from '../utils/codex-auth.js';

export async function runAuthCodex(deps = {}) {
  const loadConfigFn = deps.loadConfigFn ?? loadConfig;
  const saveConfigFn = deps.saveConfigFn ?? saveConfig;
  const writeEnvFileFn = deps.writeEnvFileFn ?? writeEnvFile;
  const setValueFn = deps.setValueFn ?? setValue;
  const getValueFn = deps.getValueFn ?? getValue;
  const loadCodexAuthFn = deps.loadCodexAuthFn ?? loadCodexAuth;

  try {
    const auth = loadCodexAuthFn();
    const summary = redactCodexAuthSummary(auth);
    const config = loadConfigFn();

    setValueFn(config, 'ai', 'authMode', 'codex_oauth');
    setValueFn(config, 'ai', 'baseUrl', 'https://api.openai.com/v1');
    setValueFn(config, 'ai', 'apiKey', '');

    const currentModel = getValueFn(config, 'ai', 'modelName');
    if (!currentModel) {
      setValueFn(config, 'ai', 'modelName', 'gpt-4.1-mini');
    }

    saveConfigFn(config);
    writeEnvFileFn(config);

    info('Đã phát hiện hồ sơ Codex OAuth hợp lệ.');
    console.log(chalk.dim(`  • auth mode: ${summary.authMode}`));
    console.log(chalk.dim(`  • auth file: ${summary.authPath}`));
    console.log(chalk.dim(`  • access token: ${summary.hasAccessToken ? 'present' : 'missing'}`));
    if (summary.lastRefresh) {
      console.log(chalk.dim(`  • last refresh: ${summary.lastRefresh}`));
    }

    success('Đã chuyển TaxSentry sang chế độ Codex OAuth. Token sẽ được đọc live từ ~/.codex/auth.json và không bị persist vào config.json.');
    success('Sếp có thể chỉnh model bằng: taxsentry config set ai.modelName <model>');

    return { config, authSummary: summary };
  } catch (err) {
    error(`Kích hoạt Codex OAuth thất bại: ${err.message}`);
    throw err;
  }
}

export default async function authCodexCommand(deps = {}) {
  await runAuthCodex(deps);
}
