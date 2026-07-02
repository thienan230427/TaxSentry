import chalk from 'chalk';
import boxen from 'boxen';
import inquirer from 'inquirer';

import {
  CODEX_API_BASE_URL,
  CODEX_LOGIN_URL,
  loadCodexAuth,
  openCodexLoginPage,
  redactCodexAuthSummary,
} from '../utils/codex-auth.js';
import { loadConfig, saveConfig, setValue, writeEnvFile } from '../config.js';
import { promptForModel } from '../onboarding.js';

function printCodexLoginInstructions(auth = null) {
  const lines = [
    chalk.bold.cyan('Codex OAuth account'),
    chalk.white(`Login URL: ${CODEX_LOGIN_URL}`),
    chalk.dim('Open the link, choose the target Gmail account, then return here.'),
  ];

  if (auth) {
    const summary = redactCodexAuthSummary(auth);
    lines.push(chalk.green(`Current profile: ${summary.accountEmail || summary.accountName || 'linked account'}`));
    lines.push(chalk.dim(`Account ID: ${summary.accountId || 'n/a'} | Last refresh: ${summary.lastRefresh || 'n/a'}`));
  }

  console.log(boxen(lines.join('\n'), { padding: 1, borderStyle: 'round', borderColor: 'cyan' }));
}

async function promptText(questions, prompt) {
  return prompt(questions);
}

async function chooseCodexCredentials({ existingAuth, prompt }) {
  if (!existingAuth) return 'reauthenticate';

  const answer = await promptText([
    {
      type: 'list',
      name: 'credentials',
      message: 'OpenAI Codex credentials',
      choices: [
        { name: 'Use existing credentials', value: 'existing' },
        { name: 'Reauthenticate (new OAuth login)', value: 'reauthenticate' },
        { name: 'Cancel', value: 'cancel' },
      ],
      default: 'existing',
    },
  ], prompt);
  return answer.credentials || 'existing';
}

export async function runAuthCodex({
  prompt = inquirer.prompt.bind(inquirer),
  loadAuth = loadCodexAuth,
  openLoginPage = openCodexLoginPage,
  fetchImpl = globalThis.fetch,
} = {}) {
  let auth = null;
  try {
    auth = loadAuth();
  } catch {
    auth = null;
  }

  printCodexLoginInstructions(auth);
  const credentialsChoice = await chooseCodexCredentials({ existingAuth: auth, prompt });
  if (credentialsChoice === 'cancel') {
    console.log(chalk.yellow('Codex OAuth login cancelled.'));
    return { skipped: true };
  }

  if (credentialsChoice === 'reauthenticate') {
    console.log(chalk.dim('\nStarting a fresh OpenAI Codex login...\n'));
    const linkChoice = await promptText([
      {
        type: 'confirm',
        name: 'openLogin',
        message: 'Open Codex login page now?',
        default: true,
      },
    ], prompt);

    if (linkChoice.openLogin) {
      const opened = openLoginPage(CODEX_LOGIN_URL);
      console.log(opened
        ? chalk.green('Opened the Codex login page in your browser.')
        : chalk.yellow(`Could not auto-open a browser. Open this URL manually: ${CODEX_LOGIN_URL}`));
    } else {
      console.log(chalk.yellow(`Open this URL manually: ${CODEX_LOGIN_URL}`));
    }

    await promptText([
      {
        type: 'input',
        name: 'continue',
        message: 'Press Enter after you finish selecting the Gmail account and signing in',
        default: '',
      },
    ], prompt);
    auth = loadAuth();
  }

  if (!auth) auth = loadAuth();

  const config = loadConfig();
  const currentModel = config.provider?.authMode === 'codex_oauth' ? config.provider.model : '';
  setValue(config, 'provider', 'kind', 'codex_oauth');
  setValue(config, 'provider', 'authMode', 'codex_oauth');
  setValue(config, 'provider', 'baseUrl', CODEX_API_BASE_URL);
  setValue(config, 'provider', 'apiKey', '');
  const model = await promptForModel({
    prompt,
    providerKind: 'codex_oauth',
    baseUrl: CODEX_API_BASE_URL,
    authMode: 'codex_oauth',
    accessToken: auth.accessToken,
    currentModel,
    fetchImpl,
  });
  setValue(config, 'provider', 'model', model);
  saveConfig(config);
  writeEnvFile(config);

  console.log(boxen([
    chalk.bold.cyan('Codex OAuth linked'),
    chalk.white(`Login URL: ${CODEX_LOGIN_URL}`),
    chalk.white(`Model: ${model}`),
    chalk.green(`Account: ${JSON.stringify(redactCodexAuthSummary(auth))}`),
  ].join('\n'), { padding: 1, borderStyle: 'round', borderColor: 'green' }));
  return { skipped: false, auth, model, config };
}

export default async function authCodexCommand(deps = {}) {
  try {
    await runAuthCodex(deps);
  } catch (error) {
    console.error(chalk.red(error.message || String(error)));
    console.log(chalk.yellow(`Open the Codex login page here: ${CODEX_LOGIN_URL}`));
    if (openCodexLoginPage(CODEX_LOGIN_URL)) {
      console.log(chalk.green('Opened the login page in your browser.'));
    }
    process.exitCode = 1;
  }
}
