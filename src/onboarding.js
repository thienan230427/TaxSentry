import chalk from 'chalk';
import boxen from 'boxen';
import inquirer from 'inquirer';

import {
  CODEX_API_BASE_URL,
  CODEX_LOGIN_URL,
  CODEX_RECOMMENDED_MODELS,
  loadCodexAuth,
  openCodexLoginPage,
  orderCodexModelIds,
  redactCodexAuthSummary,
} from './utils/codex-auth.js';
import { describeConfig, getEmptyConfig, loadConfig, saveConfig, setValue, writeEnvFile } from './config.js';

const MODEL_PICKER_LIMIT = 24;
const MODEL_FETCH_TIMEOUT_MS = 2500;
const MODEL_SEARCH_TRIGGER = 8;

const MODEL_SUGGESTIONS = {
  lmstudio: ['google/gemma-4-e4b', 'llama-3.1-8b-instruct', 'qwen2.5-coder-7b-instruct'],
  codex_oauth: CODEX_RECOMMENDED_MODELS,
  openai_api: ['gpt-4.1-mini', 'gpt-4.1', 'gpt-4o-mini', 'o4-mini'],
  openrouter: ['openai/gpt-4.1-mini', 'anthropic/claude-3.5-sonnet', 'google/gemini-2.0-flash-001'],
  custom: ['gpt-4.1-mini', 'gpt-4.1', 'gpt-4o-mini', 'claude-3-5-sonnet'],
};

const API_KEY_PRESETS = {
  openai_api: {
    label: 'OpenAI API key',
    baseUrl: 'https://api.openai.com/v1',
    apiKeyMessage: 'OpenAI API key',
  },
  openrouter: {
    label: 'OpenRouter',
    baseUrl: 'https://openrouter.ai/api/v1',
    apiKeyMessage: 'OpenRouter API key',
  },
};

const SETUP_ACCENT = chalk.hex('#f0a27a');

function banner() {
  const text = [
    chalk.bold.cyan('TaxSentry Setup Wizard'),
    chalk.dim('Provider-first setup with local memory, OAuth, and terminal chat.'),
    '',
    chalk.white('Use the arrow keys to move through each setup step.'),
  ].join('\n');
  return boxen(text, { padding: 1, borderStyle: 'single', borderColor: 'gray' });
}

function printWizardStep(title, lines = []) {
  console.log('');
  console.log(`${chalk.cyan('◇')}  ${SETUP_ACCENT.bold(title)}`);
  for (const line of lines) {
    console.log(`${chalk.cyan('│')}  ${line}`);
  }
}

function radioLine(label, detail = '', { selected = false, muted = false } = {}) {
  const marker = selected ? chalk.green('●') : chalk.gray('○');
  const labelColor = selected ? chalk.bold.white : muted ? chalk.dim : chalk.gray;
  const suffix = detail ? chalk.dim(` ${detail}`) : '';
  return `${marker} ${labelColor(label)}${suffix}`;
}

function resolveProviderChoice(config) {
  if (config.provider?.authMode === 'codex_oauth') return 'codex_oauth';
  if (config.provider?.kind === 'lmstudio') return 'lmstudio';
  if (config.provider?.baseUrl === API_KEY_PRESETS.openai_api.baseUrl) return 'openai_api';
  if (config.provider?.baseUrl === API_KEY_PRESETS.openrouter.baseUrl) return 'openrouter';
  return config.provider?.kind || 'lmstudio';
}

function providerChoices(config) {
  const active = resolveProviderChoice(config);

  return [
    {
      name: radioLine('LM Studio', '(local model server)', { selected: active === 'lmstudio' }),
      value: 'lmstudio',
    },
    {
      name: radioLine('OpenAI Codex OAuth', '(choose Gmail account in browser)', { selected: active === 'codex_oauth' }),
      value: 'codex_oauth',
    },
    {
      name: radioLine('OpenAI', '(API key)', { selected: active === 'openai_api' }),
      value: 'openai_api',
    },
    {
      name: radioLine('OpenRouter', '(API key gateway)', { selected: active === 'openrouter' }),
      value: 'openrouter',
    },
    {
      name: radioLine('Custom endpoint', '(OpenAI-compatible)', { selected: active === 'custom' }),
      value: 'custom',
    },
    {
      name: radioLine('Skip for now', '(keep current provider)', { muted: true }),
      value: 'skip',
    },
  ];
}

function printProviderMenuPreview(config) {
  const choices = providerChoices(config);
  printWizardStep('Model/auth provider', choices.map((choice) => choice.name));
}

function printCodexOAuthPanel(auth = null) {
  const lines = [
    chalk.white(`Login URL: ${CODEX_LOGIN_URL}`),
    chalk.dim('Open the link, choose the target Gmail account, then return here.'),
  ];

  if (auth) {
    const summary = redactCodexAuthSummary(auth);
    lines.push(chalk.green(`Current profile: ${summary.accountEmail || summary.accountName || 'linked account'}`));
    lines.push(chalk.dim(`Account ID: ${summary.accountId || 'n/a'} | Last refresh: ${summary.lastRefresh || 'n/a'}`));
  }

  printWizardStep('Codex OAuth account', lines);
}

function codexAuthFingerprint(auth = null) {
  if (!auth) return '';
  return [
    auth.accountId || '',
    auth.accountEmail || '',
    auth.lastRefresh || '',
    auth.accessToken ? 'access' : '',
    auth.refreshToken ? 'refresh' : '',
  ].join('|');
}

async function chooseCodexCredentialMode({ prompt, auth }) {
  if (!auth) return 'reauthenticate';

  const answer = await promptText([
    {
      type: 'list',
      name: 'credentials',
      message: 'OpenAI Codex credentials',
      choices: [
        { name: 'Use existing credentials', value: 'existing' },
        { name: 'Reauthenticate / switch account in browser', value: 'reauthenticate' },
        { name: 'Cancel Codex OAuth setup', value: 'cancel' },
      ],
      default: 'reauthenticate',
    },
  ], prompt);
  return answer.credentials || 'reauthenticate';
}

async function runCodexBrowserLogin({ prompt }) {
  const linkChoice = await promptText([
    {
      type: 'confirm',
      name: 'openLogin',
      message: 'Open Codex login page now?',
      default: true,
    },
  ], prompt);
  if (linkChoice.openLogin) {
    const opened = openCodexLoginPage(CODEX_LOGIN_URL);
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
  if (provider.baseUrl === API_KEY_PRESETS.openai_api.baseUrl) return 'OpenAI API key';
  if (provider.baseUrl === API_KEY_PRESETS.openrouter.baseUrl) return 'OpenRouter';
  return 'Custom OpenAI-compatible';
}

function uniqueStrings(values) {
  return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))];
}

function resolveModelFallback(providerKind) {
  const suggestions = MODEL_SUGGESTIONS[providerKind] || MODEL_SUGGESTIONS.custom;
  return suggestions[0] || 'gpt-4.1-mini';
}

async function fetchModelIds({ baseUrl, apiKey = '', authMode = '', accessToken = '', fetchImpl = globalThis.fetch } = {}) {
  if (typeof fetchImpl !== 'function' || !baseUrl) return [];

  let url;
  try {
    url = new URL('/models', baseUrl.endsWith('/') ? baseUrl : `${baseUrl}/`).toString();
  } catch {
    return [];
  }

  const headers = { Accept: 'application/json' };
  if (authMode === 'codex_oauth' && accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  } else if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }

  try {
    const signal = typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
      ? AbortSignal.timeout(MODEL_FETCH_TIMEOUT_MS)
      : undefined;
    const response = await fetchImpl(url, { headers, signal });
    if (!response.ok) return [];

    const payload = await response.json();
    const rawModels = Array.isArray(payload?.data)
      ? payload.data.map((item) => item?.id || item?.name || item)
      : Array.isArray(payload)
        ? payload
        : [];
    const models = uniqueStrings(rawModels);
    return authMode === 'codex_oauth'
      ? orderCodexModelIds(models).slice(0, MODEL_PICKER_LIMIT)
      : models.slice(0, MODEL_PICKER_LIMIT);
  } catch {
    return [];
  }
}

function printModelMenu(modelIds, { providerKind, currentModel, fallbackModel }) {
  const providerLabel = providerKind === 'lmstudio'
    ? 'LM Studio'
    : providerKind === 'codex_oauth'
      ? 'Codex OAuth'
      : API_KEY_PRESETS[providerKind]?.label || 'Custom endpoint';
  const lines = [
    chalk.dim('Choose by number, type `s` to search, `c` for custom, Enter for default.'),
    [
      chalk.blue('[recent]'),
      chalk.green('[recommended]'),
      chalk.magenta('[custom]'),
    ].join(' '),
    '',
  ];
  for (const [index, modelId] of modelIds.entries()) {
    const badge = modelId === currentModel && currentModel
      ? chalk.blue('recent')
      : index === 0
        ? chalk.green('recommended')
        : '';
    const suffix = badge ? ` ${chalk.dim(`[${badge}]`)}` : '';
    lines.push(`${chalk.bold(String(index + 1).padStart(2, '0'))}. ${modelId}${suffix}`);
  }
  if (fallbackModel && !modelIds.includes(fallbackModel)) {
    lines.push(`${chalk.bold(String(modelIds.length + 1).padStart(2, '0'))}. ${fallbackModel} ${chalk.dim(`[${chalk.green('recommended')}]`)}`);
  }
  if (modelIds.length >= MODEL_SEARCH_TRIGGER) {
    lines.push(chalk.dim('Type `s` to filter large model lists.'));
  }
  lines.push(`${chalk.bold(' c')}. ${chalk.magenta('Enter another model name')}`);
  printWizardStep(`${providerLabel} model`, lines);
}

async function promptForCustomModel({ prompt, fallbackModel }) {
  const answer = await promptText([
    {
      type: 'input',
      name: 'model',
      message: 'Model name',
      default: fallbackModel,
    },
  ], prompt);
  return answer.model || fallbackModel;
}

async function promptForSearchQuery({ prompt, fallbackQuery = '' }) {
  const answer = await promptText([
    {
      type: 'input',
      name: 'query',
      message: 'Search models',
      default: fallbackQuery,
    },
  ], prompt);
  return String(answer.query || '').trim();
}

async function selectModelFromMenu({ prompt, modelIds, providerKind, currentModel, fallbackModel }) {
  printModelMenu(modelIds, { providerKind, currentModel, fallbackModel });
  const answer = await promptText([
    {
      type: 'input',
      name: 'selection',
      message: 'Model name',
      default: '1',
    },
  ], prompt);

  const selection = String(answer.selection || '').trim();
  if (!selection) return modelIds[0] || fallbackModel;
  if (/^c$/i.test(selection) || /^custom$/i.test(selection)) {
    return promptForCustomModel({ prompt, fallbackModel });
  }
  if (/^s$/i.test(selection) || /^search$/i.test(selection)) {
    const query = await promptForSearchQuery({ prompt, fallbackQuery: fallbackModel });
    if (!query) {
      return selectModelFromMenu({ prompt, modelIds, providerKind, currentModel, fallbackModel });
    }

    const filtered = modelIds.filter((modelId) => modelId.toLowerCase().includes(query.toLowerCase()));
    if (filtered.length === 0) {
      console.log(chalk.yellow(`Không tìm thấy model nào khớp "${query}".`));
      return selectModelFromMenu({ prompt, modelIds, providerKind, currentModel, fallbackModel });
    }
    return selectModelFromMenu({
      prompt,
      modelIds: filtered,
      providerKind,
      currentModel: filtered.includes(currentModel) ? currentModel : '',
      fallbackModel: filtered.includes(fallbackModel) ? fallbackModel : filtered[0],
    });
  }

  const selectionNumber = Number.parseInt(selection, 10);
  if (!Number.isNaN(selectionNumber) && selectionNumber >= 1 && selectionNumber <= modelIds.length) {
    return modelIds[selectionNumber - 1];
  }

  const matched = modelIds.find((modelId) => modelId.toLowerCase() === selection.toLowerCase());
  if (matched) return matched;
  return selection;
}

export async function promptForModel({
  prompt,
  providerKind,
  baseUrl,
  apiKey,
  authMode,
  accessToken,
  currentModel,
  fetchImpl = globalThis.fetch,
}) {
  const fallbackModel = resolveModelFallback(providerKind);
  const fetchedModels = await fetchModelIds({ baseUrl, apiKey, authMode, accessToken, fetchImpl });
  const preferredModel = currentModel || fallbackModel;
  const modelIds = uniqueStrings([
    preferredModel,
    ...fetchedModels,
    ...(MODEL_SUGGESTIONS[providerKind] || MODEL_SUGGESTIONS.custom),
  ]).slice(0, MODEL_PICKER_LIMIT);

  if (modelIds.length === 0) {
    return promptForCustomModel({ prompt, fallbackModel });
  }

  return selectModelFromMenu({ prompt, modelIds, providerKind, currentModel, fallbackModel });
}

async function configureApiKeyProvider({ config, prompt, providerKind, currentModel }) {
  const preset = API_KEY_PRESETS[providerKind];
  const answer = await promptText([
    {
      type: 'input',
      name: 'apiKey',
      message: preset.apiKeyMessage,
      default: config.provider.apiKey || '',
    },
  ], prompt);

  setValue(config, 'provider', 'kind', 'custom');
  setValue(config, 'provider', 'authMode', 'api_key');
  setValue(config, 'provider', 'baseUrl', preset.baseUrl);
  setValue(config, 'provider', 'apiKey', answer.apiKey || '');
  const model = await promptForModel({
    prompt,
    providerKind,
    baseUrl: preset.baseUrl,
    apiKey: answer.apiKey || '',
    authMode: 'api_key',
    currentModel,
  });
  setValue(config, 'provider', 'model', model);
}

export async function runOnboarding({ resetExisting = false, prompt = inquirer.prompt.bind(inquirer) } = {}) {
  const base = resetExisting ? getEmptyConfig() : loadConfig();
  const config = nextConfig(base);
  const rememberedModel = resetExisting ? '' : config.provider.model || '';

  console.log(banner());
  printWizardStep('Agent profile', [
    chalk.dim('Name, persona, and default language for the local assistant.'),
  ]);

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
  setValue(config, 'agent', 'llmPlannerEnabled', Boolean(config.agent.llmPlannerEnabled));

  printProviderMenuPreview(config);
  const providerChoice = await promptText([
    {
      type: 'list',
      name: 'provider',
      message: 'Select provider',
      choices: providerChoices(config),
      default: resolveProviderChoice(config),
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
    ], prompt);
    setValue(config, 'provider', 'kind', 'lmstudio');
    setValue(config, 'provider', 'authMode', 'lmstudio');
    setValue(config, 'provider', 'baseUrl', answer.baseUrl || 'http://localhost:1234/v1');
    const model = await promptForModel({
      prompt,
      providerKind: 'lmstudio',
      baseUrl: config.provider.baseUrl || answer.baseUrl || 'http://localhost:1234/v1',
      authMode: 'lmstudio',
      currentModel: rememberedModel,
    });
    setValue(config, 'provider', 'model', model);
    setValue(config, 'provider', 'apiKey', '');
  } else if (providerChoice.provider === 'openai_api' || providerChoice.provider === 'openrouter') {
    await configureApiKeyProvider({
      config,
      prompt,
      providerKind: providerChoice.provider,
      currentModel: rememberedModel,
    });
  } else if (providerChoice.provider === 'codex_oauth') {
    let codexAuth = null;
    try {
      codexAuth = loadCodexAuth();
    } catch {
      codexAuth = null;
    }
    printCodexOAuthPanel(codexAuth);
    const previousAuthFingerprint = codexAuthFingerprint(codexAuth);
    const credentialMode = await chooseCodexCredentialMode({ prompt, auth: codexAuth });
    if (credentialMode === 'cancel') {
      console.log(chalk.yellow('Codex OAuth setup cancelled; keeping the current provider configuration.'));
    } else {
      if (credentialMode === 'reauthenticate') {
        await runCodexBrowserLogin({ prompt });
        try {
          codexAuth = loadCodexAuth();
        } catch (error) {
          console.log(chalk.yellow(`Codex OAuth check: ${String(error.message || error)}`));
        }
        if (previousAuthFingerprint && codexAuthFingerprint(codexAuth) === previousAuthFingerprint) {
          console.log(chalk.yellow([
            'Codex OAuth profile did not change after browser login.',
            'If Chrome opened the Codex home page instead of account selection, it is reusing the current ChatGPT session.',
            'To switch accounts, sign out from ChatGPT/Codex in the browser or use another browser profile, then run this step again.',
          ].join(' ')));
        }
      }
      if (codexAuth) {
        console.log(chalk.green(`Codex OAuth linked: ${JSON.stringify(redactCodexAuthSummary(codexAuth))}`));
      }
      setValue(config, 'provider', 'kind', 'codex_oauth');
      setValue(config, 'provider', 'authMode', 'codex_oauth');
      setValue(config, 'provider', 'baseUrl', CODEX_API_BASE_URL);
      const model = await promptForModel({
        prompt,
        providerKind: 'codex_oauth',
        baseUrl: CODEX_API_BASE_URL,
        authMode: 'codex_oauth',
        accessToken: codexAuth?.accessToken || '',
        currentModel: rememberedModel,
      });
      setValue(config, 'provider', 'model', model);
      setValue(config, 'provider', 'apiKey', '');
    }
  } else if (providerChoice.provider === 'custom') {
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
    ], prompt);
    setValue(config, 'provider', 'kind', 'custom');
    setValue(config, 'provider', 'authMode', 'api_key');
    setValue(config, 'provider', 'baseUrl', answer.baseUrl || 'https://api.openai.com/v1');
    setValue(config, 'provider', 'apiKey', answer.apiKey || '');
    const model = await promptForModel({
      prompt,
      providerKind: 'custom',
      baseUrl: answer.baseUrl || 'https://api.openai.com/v1',
      apiKey: answer.apiKey || '',
      authMode: 'api_key',
      currentModel: rememberedModel,
    });
    setValue(config, 'provider', 'model', model);
  }

  printWizardStep('Memory policy', [
    chalk.dim('Session title and context limits for future chat turns.'),
  ]);
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

  printWizardStep('Select channel (QuickStart)', [
    radioLine('Telegram', '(Bot API)', { selected: Boolean(config.integrations.telegram.enabled) }),
    radioLine('Skip for now', '', { selected: !config.integrations.telegram.enabled }),
  ]);
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
