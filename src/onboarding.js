import chalk from 'chalk';
import boxen from 'boxen';
import inquirer from 'inquirer';

import { loadCodexAuth, redactCodexAuthSummary } from './utils/codex-auth.js';
import { describeConfig, getEmptyConfig, loadConfig, saveConfig, setValue, writeEnvFile } from './config.js';

function banner() {
  const text = [
    chalk.bold.cyan('TaxSentry Setup Wizard'),
    chalk.dim('Provider-first setup with local memory and friendly defaults.'),
    '',
    chalk.white('Choose one of the supported providers:'),
  ].join('\n');
  return boxen(text, { padding: 1, borderStyle: 'round', borderColor: 'cyan' });
}

function printProviderCards() {
  const cards = [
    [chalk.bold('LM Studio'), chalk.green('Local OpenAI-compatible server'), chalk.dim('http://localhost:1234/v1 · zero cloud dependency')],
    [chalk.bold('OpenAI Codex OAuth'), chalk.yellow('Use existing Codex login'), chalk.dim('Great if the user already authenticated via Codex CLI')],
    [chalk.bold('Custom endpoint'), chalk.magenta('Any OpenAI-compatible provider'), chalk.dim('Bring your own URL, model, and API key')],
  ];
  console.log('');
  for (const [title, subtitle, footer] of cards) {
    console.log(boxen([title, subtitle, footer].join('\n'), { padding: 1, borderStyle: 'round', borderColor: 'gray' }));
  }
}

function promptText(questions, prompt) {
  return prompt(questions);
}

function nextConfig(base) {
  const config = JSON.parse(JSON.stringify(base));
  if (!config.provider) config.provider = {};
  if (!config.agent) config.agent = {};
  if (!config.memory) config.memory = {};
  if (!config.integrations) config.integrations = { telegram: {} };
  if (!config.integrations.telegram) config.integrations.telegram = {};
  return config;
}

function chooseProviderSummary(provider) {
  if (provider.authMode === 'codex_oauth') return 'OpenAI Codex OAuth';
  if (provider.kind === 'lmstudio') return 'LM Studio';
  return 'Custom OpenAI-compatible';
}

export async function runOnboarding({ resetExisting = false, prompt = inquirer.prompt.bind(inquirer) } = {}) {
  const base = resetExisting ? getEmptyConfig() : loadConfig();
  const config = nextConfig(base);

  console.log(banner());
  printProviderCards();

  const intro = await promptText([
    {
      type: 'input',
      name: 'name',
      message: 'Agent name',
      default: config.agent.name || 'TaxSentry',
    },
    {
      type: 'input',
      name: 'persona',
      message: 'Agent persona',
      default: config.agent.persona || 'warm, precise, and practical',
    },
    {
      type: 'list',
      name: 'language',
      message: 'Default language',
      choices: [
        { name: 'Vietnamese (vi)', value: 'vi' },
        { name: 'English (en)', value: 'en' },
      ],
      default: config.agent.language || 'vi',
    },
  ], prompt);

  setValue(config, 'agent', 'name', intro.name || 'TaxSentry');
  setValue(config, 'agent', 'persona', intro.persona || 'warm, precise, and practical');
  setValue(config, 'agent', 'language', intro.language || 'vi');
  setValue(config, 'agent', 'memoryEnabled', true);

  const providerChoice = await promptText([
    {
      type: 'list',
      name: 'provider',
      message: 'Select provider',
      choices: [
        { name: 'LM Studio — local-first, zero cloud dependency', value: 'lmstudio' },
        { name: 'OpenAI Codex OAuth — reuse Codex login', value: 'codex_oauth' },
        { name: 'Custom OpenAI-compatible endpoint', value: 'custom' },
      ],
      default: config.provider.authMode === 'codex_oauth' ? 'codex_oauth' : config.provider.kind || 'lmstudio',
    },
  ], prompt);

  if (providerChoice.provider === 'lmstudio') {
    const answer = await promptText([
      {
        type: 'input',
        name: 'baseUrl',
        message: 'LM Studio endpoint',
        default: config.provider.baseUrl || 'http://localhost:1234/v1',
      },
      {
        type: 'input',
        name: 'model',
        message: 'Model name',
        default: config.provider.model || 'google/gemma-4-e4b',
      },
    ], prompt);
    setValue(config, 'provider', 'kind', 'lmstudio');
    setValue(config, 'provider', 'authMode', 'lmstudio');
    setValue(config, 'provider', 'baseUrl', answer.baseUrl || 'http://localhost:1234/v1');
    setValue(config, 'provider', 'model', answer.model || 'google/gemma-4-e4b');
    setValue(config, 'provider', 'apiKey', '');
  } else if (providerChoice.provider === 'codex_oauth') {
    let codexSummary = '';
    try {
      const auth = loadCodexAuth();
      codexSummary = JSON.stringify(redactCodexAuthSummary(auth));
    } catch (error) {
      codexSummary = String(error.message || error);
    }
    console.log(chalk.yellow(`\nCodex OAuth check: ${codexSummary}`));
    const answer = await promptText([
      {
        type: 'input',
        name: 'model',
        message: 'Model name',
        default: config.provider.model || 'gpt-4.1',
      },
    ], prompt);
    setValue(config, 'provider', 'kind', 'codex_oauth');
    setValue(config, 'provider', 'authMode', 'codex_oauth');
    setValue(config, 'provider', 'baseUrl', 'https://api.openai.com/v1');
    setValue(config, 'provider', 'model', answer.model || 'gpt-4.1');
    setValue(config, 'provider', 'apiKey', '');
  } else {
    const answer = await promptText([
      {
        type: 'input',
        name: 'baseUrl',
        message: 'OpenAI-compatible base URL',
        default: config.provider.baseUrl || 'https://api.openai.com/v1',
      },
      {
        type: 'input',
        name: 'apiKey',
        message: 'API key',
        default: config.provider.apiKey || '',
      },
      {
        type: 'input',
        name: 'model',
        message: 'Model name',
        default: config.provider.model || 'gpt-4.1-mini',
      },
    ], prompt);
    setValue(config, 'provider', 'kind', 'custom');
    setValue(config, 'provider', 'authMode', 'api_key');
    setValue(config, 'provider', 'baseUrl', answer.baseUrl || 'https://api.openai.com/v1');
    setValue(config, 'provider', 'apiKey', answer.apiKey || '');
    setValue(config, 'provider', 'model', answer.model || 'gpt-4.1-mini');
  }

  const memory = await promptText([
    {
      type: 'input',
      name: 'sessionTitle',
      message: 'Default session title',
      default: config.memory.sessionTitle || `${config.agent.name} session`,
    },
    {
      type: 'number',
      name: 'maxFacts',
      message: 'How many memory facts should be injected into the prompt?',
      default: config.memory.maxFacts || 50,
    },
    {
      type: 'number',
      name: 'maxTurns',
      message: 'How many recent turns should be remembered?',
      default: config.memory.maxTurns || 12,
    },
  ], prompt);

  setValue(config, 'memory', 'sessionTitle', memory.sessionTitle || `${config.agent.name} session`);
  setValue(config, 'memory', 'maxFacts', Number(memory.maxFacts) || 50);
  setValue(config, 'memory', 'maxTurns', Number(memory.maxTurns) || 12);

  const telegram = await promptText([
    {
      type: 'confirm',
      name: 'enabled',
      message: 'Enable Telegram notifications?',
      default: Boolean(config.integrations.telegram.enabled),
    },
  ], prompt);

  config.integrations.telegram = {
    enabled: Boolean(telegram.enabled),
    botToken: config.integrations.telegram.botToken || '',
    adminChatId: config.integrations.telegram.adminChatId || '',
  };

  if (telegram.enabled) {
    const tg = await promptText([
      {
        type: 'input',
        name: 'botToken',
        message: 'Telegram bot token',
        default: config.integrations.telegram.botToken || '',
      },
      {
        type: 'input',
        name: 'adminChatId',
        message: 'Telegram admin chat ID',
        default: config.integrations.telegram.adminChatId || '',
      },
    ], prompt);
    config.integrations.telegram.botToken = tg.botToken || '';
    config.integrations.telegram.adminChatId = tg.adminChatId || '';
  }

  config.configured = true;
  saveConfig(config);
  writeEnvFile(config);

  console.log('\n' + boxen(describeConfig(config), { padding: 1, borderStyle: 'round', borderColor: 'green' }));
  console.log(chalk.green.bold(`\nSetup complete — ${chooseProviderSummary(config.provider)} is ready.`));
  return config;
}
