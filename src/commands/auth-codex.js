import chalk from 'chalk';

import { loadCodexAuth, redactCodexAuthSummary } from '../utils/codex-auth.js';
import { loadConfig, saveConfig, setValue, writeEnvFile } from '../config.js';

export default async function authCodexCommand() {
  try {
    const auth = loadCodexAuth();
    const config = loadConfig();
    setValue(config, 'provider', 'kind', 'codex_oauth');
    setValue(config, 'provider', 'authMode', 'codex_oauth');
    setValue(config, 'provider', 'baseUrl', 'https://api.openai.com/v1');
    setValue(config, 'provider', 'apiKey', '');
    saveConfig(config);
    writeEnvFile(config);
    console.log(chalk.green(`Codex OAuth linked: ${JSON.stringify(redactCodexAuthSummary(auth))}`));
  } catch (error) {
    console.error(chalk.red(error.message || String(error)));
    process.exitCode = 1;
  }
}
