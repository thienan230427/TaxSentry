import chalk from 'chalk';
import boxen from 'boxen';
import inquirer from 'inquirer';

import { loadCodexAuth, redactCodexAuthSummary } from './utils/codex-auth.js';
import { describeConfig, getEmptyConfig, loadConfig, saveConfig, setValue, writeEnvFile } from './config.js';

const MODEL_PICKER_LIMIT = 24;
const MODEL_FETCH_TIMEOUT_MS = 2500;
const MODEL_SEARCH_TRIGGER = 8;

const MODEL_SUGGESTIONS = {
  lmstudio: ['google/gemma-4-e4b', 'llama-3.1-8b-instruct', 'qwen2.5-coder-7b-instruct'],
  codex_oauth: ['gpt-4.1', 'gpt-4.1-mini', 'gpt-4o', 'o4-mini'],
  custom: ['gpt-4.1-mini', 'gpt-4.1', 'gpt-4o-mini', 'claude-3-5-sonnet'],
};

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
  const cards = ['lmstudio', 'codex_oauth', 'custom'].map((kind) => providerTheme(kind));
  console.log(chalk.cyan('\nProvider cockpit'));
  console.log(chalk.dim('Select provider with the arrows, then press Enter to confirm.'));
  console.log([chalk.green('[local]'), chalk.yellow('[oauth]'), chalk.magenta('[flex]')].join(' '));
  console.log('');
  for (const card of cards) {
    console.log(boxen([`${card.badge} ${chalk.bold(card.label)}`, card.accent(card.detail), chalk.dim(card.footer)].join('\n'), { padding: 1, borderStyle: 'round', borderColor: 'gray' }));
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

function providerTheme(kind) {
  if (kind === 'lmstudio') {
    return {
      badge: chalk.green('[local]'),
      accent: chalk.green,
      label: 'LM Studio',
      detail: 'Local OpenAI-compatible server',
      footer: 'http://localhost:1234/v1 · zero cloud dependency',
    };
  }
  if (kind === 'codex_oauth') {
    return {
      badge: chalk.yellow('[oauth]'),
      accent: chalk.yellow,
      label: 'OpenAI Codex OAuth',
      detail: 'Use existing Codex login',
      footer: 'Great if the user already authenticated via Codex CLI',
    };
  }
  return {
    badge: chalk.magenta('[flex]'),
    accent: chalk.magenta,
    label: 'Custom endpoint',
    detail: 'Any OpenAI-compatible provider',
    footer: 'Bring your own URL, model, and API key',
  };
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
    return uniqueStrings(rawModels).slice(0, MODEL_PICKER_LIMIT);
  } catch {
    return [];
  }
}

function printModelMenu(modelIds, { providerKind, currentModel, fallbackModel }) {
  const providerLabel = providerKind === 'lmstudio'
    ? 'LM Studio'
    : providerKind === 'codex_oauth'
      ? 'Codex OAuth'
      : 'Custom endpoint';
  console.log(chalk.cyan(`\n${providerLabel} model menu`));
  console.log(chalk.dim('Chọn bằng số, gõ `s` để tìm, `c` để nhập tay, hoặc Enter để dùng model đầu tiên.'));
  console.log(
    [
      chalk.blue('[recent]'),
      chalk.green('[recommended]'),
      chalk.magenta('[custom]'),
    ].join(' '),
  );
  console.log('');
  for (const [index, modelId] of modelIds.entries()) {
    const badge = modelId === currentModel && currentModel
      ? chalk.blue('recent')
      : index === 0
        ? chalk.green('recommended')
        : '';
    const suffix = badge ? ` ${chalk.dim(`[${badge}]`)}` : '';
    console.log(`${chalk.bold(String(index + 1).padStart(2, '0'))}. ${modelId}${suffix}`);
  }
  if (fallbackModel && !modelIds.includes(fallbackModel)) {
    console.log(`${chalk.bold(String(modelIds.length + 1).padStart(2, '0'))}. ${fallbackModel} ${chalk.dim(`[${chalk.green('recommended')}]`)}`);
  }
  if (modelIds.length >= MODEL_SEARCH_TRIGGER) {
    console.log(chalk.dim('gõ `s` để lọc nhanh theo tên model khi danh sách dài'));
  }
  console.log(`${chalk.bold(' c')}. ${chalk.magenta('Nhập tên model khác')}`);
  console.log('');
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

async function promptForModel({ prompt, providerKind, baseUrl, apiKey, authMode, accessToken, currentModel }) {
  const fallbackModel = resolveModelFallback(providerKind);
  const fetchedModels = await fetchModelIds({ baseUrl, apiKey, authMode, accessToken });
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

export async function runOnboarding({ resetExisting = false, prompt = inquirer.prompt.bind(inquirer) } = {}) {
  const base = resetExisting ? getEmptyConfig() : loadConfig();
  const config = nextConfig(base);
  const rememberedModel = resetExisting ? '' : config.provider.model || '';

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
  } else if (providerChoice.provider === 'codex_oauth') {
    let codexSummary = '';
    let codexAuth = null;
    try {
      codexAuth = loadCodexAuth();
      codexSummary = JSON.stringify(redactCodexAuthSummary(codexAuth));
    } catch (error) {
      codexSummary = String(error.message || error);
    }
    console.log(chalk.yellow(`\nCodex OAuth check: ${codexSummary}`));
    setValue(config, 'provider', 'kind', 'codex_oauth');
    setValue(config, 'provider', 'authMode', 'codex_oauth');
    setValue(config, 'provider', 'baseUrl', 'https://api.openai.com/v1');
    const model = await promptForModel({
      prompt,
      providerKind: 'codex_oauth',
      baseUrl: 'https://api.openai.com/v1',
      authMode: 'codex_oauth',
      accessToken: codexAuth?.accessToken || '',
      currentModel: rememberedModel,
    });
    setValue(config, 'provider', 'model', model);
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
