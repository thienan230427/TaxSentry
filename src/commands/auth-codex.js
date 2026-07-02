import chalk from 'chalk';
import boxen from 'boxen';

import {
  CODEX_LOGIN_URL,
  loadCodexAuth,
  openCodexLoginPage,
  redactCodexAuthSummary,
} from '../utils/codex-auth.js';
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
    console.log(boxen([
      chalk.bold.cyan('Codex OAuth linked'),
      chalk.white(`Login URL: ${CODEX_LOGIN_URL}`),
      chalk.green(`Account: ${JSON.stringify(redactCodexAuthSummary(auth))}`),
    ].join('\n'), { padding: 1, borderStyle: 'round', borderColor: 'green' }));
  } catch (error) {
    console.error(chalk.red(error.message || String(error)));
    console.log(chalk.yellow(`Open the Codex login page here: ${CODEX_LOGIN_URL}`));
    if (openCodexLoginPage(CODEX_LOGIN_URL)) {
      console.log(chalk.green('Opened the login page in your browser.'));
    }
    process.exitCode = 1;
  }
}
