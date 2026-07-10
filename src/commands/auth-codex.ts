import chalk from 'chalk';
import inquirer from 'inquirer';

import {
  CODEX_API_BASE_URL,
  CODEX_DEVICE_LOGIN_URL,
  loadCodexAuth,
  openCodexLoginPage,
  redactCodexAuthSummary,
  pollCodexDeviceAuth,
  requestCodexDeviceCode,
} from '../utils/codex-auth.ts';
import { loadConfig, saveConfig, setValue, writeEnvFile } from '../config.ts';
import { promptForModel } from '../onboarding.ts';
import { oceanFrame } from '../utils/terminal-theme.ts';

function printCodexLoginInstructions(auth = null, deviceCode = null) {
  const lines = [
    chalk.bold.hex('#38bdf8')('Codex OAuth account'),
    chalk.white(`Login URL: ${deviceCode?.verificationUrl || CODEX_DEVICE_LOGIN_URL}`),
    deviceCode?.userCode ? chalk.white(`One-time code: ${deviceCode.userCode}`) : chalk.dim('Requesting a one-time code...'),
    chalk.dim('Open the link, sign in, enter the code, then let the terminal continue automatically.'),
  ];

  if (auth) {
    const summary = redactCodexAuthSummary(auth);
    lines.push(chalk.green(`Current profile: ${summary.accountEmail || summary.accountName || 'linked account'}`));
    lines.push(chalk.dim(`Account ID: ${summary.accountId || 'n/a'} | Last refresh: ${summary.lastRefresh || 'n/a'}`));
  }

  console.log(oceanFrame('Codex OAuth account', lines, { subtitle: 'Blue login card', borderColor: 'blue' }));
}

async function promptText(questions, prompt) {
  return prompt(questions);
}

async function configureTelegramAfterAuth({ config, prompt }) {
  const answer = await promptText([
    {
      type: 'confirm',
      name: 'enabled',
      message: 'Configure Telegram now?',
      default: true,
    },
  ], prompt);

  if (!answer.enabled) {
    return false;
  }

  const telegram = config.integrations?.telegram || {};
  const tg = await promptText([
    {
      type: 'input',
      name: 'botToken',
      message: 'Telegram bot token',
      default: telegram.botToken || '',
    },
    {
      type: 'input',
      name: 'adminChatId',
      message: 'Telegram admin chat ID',
      default: telegram.adminChatId || '',
    },
  ], prompt);

  setValue(config, 'integrations', 'telegram', {
    enabled: true,
    botToken: tg.botToken || '',
    adminChatId: tg.adminChatId || '',
  });
  saveConfig(config);
  writeEnvFile(config);
  return true;
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
      default: 'reauthenticate',
    },
  ], prompt);
  return answer.credentials || 'reauthenticate';
}

export async function runAuthCodex({
  prompt = inquirer.prompt.bind(inquirer),
  loadAuth = loadCodexAuth,
  openLoginPage = openCodexLoginPage,
  requestDeviceCode = requestCodexDeviceCode,
  pollDeviceAuth = pollCodexDeviceAuth,
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
    const deviceCode = await requestDeviceCode({ fetchImpl });
    printCodexLoginInstructions(auth, deviceCode);
    const linkChoice = await promptText([
      {
        type: 'confirm',
        name: 'openLogin',
        message: 'Open Codex login page now?',
        default: true,
      },
    ], prompt);

    if (linkChoice.openLogin) {
      const opened = openLoginPage(deviceCode.verificationUrl || CODEX_DEVICE_LOGIN_URL);
      console.log(opened
        ? chalk.green('Opened the Codex login page in your browser.')
        : chalk.yellow(`Could not auto-open a browser. Open this URL manually: ${deviceCode.verificationUrl || CODEX_DEVICE_LOGIN_URL}`));
    } else {
      console.log(chalk.yellow(`Open this URL manually: ${deviceCode.verificationUrl || CODEX_DEVICE_LOGIN_URL}`));
    }

    console.log(chalk.dim('Waiting for Codex to finish the one-time code login...'));
    auth = await pollDeviceAuth({
      fetchImpl,
      deviceAuthId: deviceCode.deviceAuthId,
      userCode: deviceCode.userCode,
      intervalMs: deviceCode.intervalMs,
    });
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

  console.log(oceanFrame(
    'Codex OAuth linked',
    [
      chalk.white(`Login URL: ${CODEX_DEVICE_LOGIN_URL}`),
      chalk.white(`Model: ${model}`),
      chalk.hex('#67e8f9')(`Account: ${JSON.stringify(redactCodexAuthSummary(auth))}`),
    ],
    { subtitle: 'Provider linked successfully', borderColor: 'blue' },
  ));

  if (await configureTelegramAfterAuth({ config, prompt })) {
    console.log(oceanFrame(
      'Telegram configured',
      [
        chalk.white(`Bot token: ${config.integrations.telegram.botToken ? 'set' : 'missing'}`),
        chalk.white(`Admin chat ID: ${config.integrations.telegram.adminChatId || 'missing'}`),
      ],
      { subtitle: 'Chat delivery ready', borderColor: 'blue' },
    ));
  }

  return { skipped: false, auth, model, config };
}

export default async function authCodexCommand(deps = {}) {
  try {
    await runAuthCodex(deps);
  } catch (error) {
    console.error(chalk.red(error.message || String(error)));
    console.log(chalk.yellow(`Open the Codex login page here: ${CODEX_DEVICE_LOGIN_URL}`));
    if (openCodexLoginPage(CODEX_DEVICE_LOGIN_URL)) {
      console.log(chalk.green('Opened the login page in your browser.'));
    }
    process.exitCode = 1;
  }
}

