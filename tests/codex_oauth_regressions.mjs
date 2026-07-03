import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const SHARED_HOME = mkdtempSync(join(tmpdir(), 'taxsentry-codex-home-'));

function applySharedHome() {
  process.env.HOME = SHARED_HOME;
  process.env.USERPROFILE = SHARED_HOME;
  process.env.HOMEDRIVE = '';
  process.env.HOMEPATH = SHARED_HOME;
  process.env.TAXSENTRY_HOME = join(SHARED_HOME, '.taxsentry');
  process.env.TAXSENTRY_CONFIG_FILE = join(SHARED_HOME, '.taxsentry', 'config', 'config.json');
  process.env.TAXSENTRY_MEMORY_DB = join(SHARED_HOME, '.taxsentry', 'memory', 'memory.db');
  process.env.TAXSENTRY_SESSION_FILE = join(SHARED_HOME, '.taxsentry', 'memory', 'sessions.jsonl');
  process.env.TAXSENTRY_CORE_DIR = join(SHARED_HOME, '.taxsentry', 'taxsentry-core');
  process.env.TAXSENTRY_ENV_FILE = join(SHARED_HOME, '.taxsentry', 'taxsentry-core', '.env');
}

function freshImport(relPath) {
  return import(pathToFileURL(join(process.cwd(), relPath)).href + `?t=${Date.now()}-${Math.random()}`);
}

applySharedHome();

const codexAuth = await freshImport('src/utils/codex-auth.js');
const {
  CODEX_LOGIN_URL,
  CODEX_RECOMMENDED_MODELS,
  fetchCodexModelIds,
  redactCodexAuthSummary,
} = codexAuth;

assert.equal(
  CODEX_LOGIN_URL,
  'https://chatgpt.com/auth/login?next=%2Fcodex%2Fcloud',
  'Codex login URL should point to the official ChatGPT account login flow',
);

assert.deepEqual(
  CODEX_RECOMMENDED_MODELS,
  ['gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex-spark'],
  'Codex OAuth fallback models should match the current Codex model IDs',
);

const summary = redactCodexAuthSummary({
  authPath: 'C:\\Users\\Admin\\.codex\\auth.json',
  authMode: 'codex_oauth',
  accessToken: 'token-123',
  refreshToken: 'refresh-456',
  accountId: 'abc123456789',
  accountEmail: 'thienan@gmail.com',
  accountName: 'Thiên Ân',
  lastRefresh: '2026-07-01T00:00:00Z',
});

assert.equal(summary.accountEmail, 'th***@gmail.com', 'account email should be masked');
assert.equal(summary.accountName, 'Thiên Ân', 'account name should be preserved');
assert.equal(summary.accountId, 'abc123…', 'account id should be shortened');

const fetchedModels = await fetchCodexModelIds({
  auth: { accessToken: 'token-123' },
  fetchImpl: async (url, options) => {
    assert.equal(url, 'https://api.openai.com/v1/models', 'Codex OAuth should fetch models from the OpenAI models endpoint');
    assert.equal(options.headers.Authorization, 'Bearer token-123', 'Codex OAuth should use the linked access token');
    return {
      ok: true,
      async json() {
        return {
          data: [
            { id: 'gpt-5.4-mini' },
            { id: 'gpt-4.1' },
            { id: 'gpt-5.5' },
          ],
        };
      },
    };
  },
});

assert.deepEqual(
  fetchedModels.slice(0, 3),
  ['gpt-5.5', 'gpt-5.4-mini', 'gpt-4.1'],
  'Codex model fetch should prioritize current recommended Codex IDs while preserving available models',
);

const { runAuthCodex } = await freshImport('src/commands/auth-codex.js');
const openedUrls = [];
let loadAuthCalls = 0;
const fakeAuth = {
  authPath: join(SHARED_HOME, '.codex', 'auth.json'),
  authMode: 'chatgpt',
  accessToken: 'token-123',
  refreshToken: 'refresh-456',
  accountId: 'abc123456789',
  accountEmail: 'thienan@gmail.com',
  accountName: 'Thiên Ân',
  lastRefresh: '2026-07-01T00:00:00Z',
};
const promptQueue = [
  { openLogin: true },
  { continue: '' },
  { selection: '1' },
];
const originalLog = console.log;
console.log = () => {};

try {
  const result = await runAuthCodex({
    prompt: async () => promptQueue.shift(),
    loadAuth: () => {
      loadAuthCalls += 1;
      if (loadAuthCalls === 1) throw new Error('missing auth');
      return fakeAuth;
    },
    openLoginPage: (url) => {
      openedUrls.push(url);
      return true;
    },
    fetchImpl: async () => ({
      ok: true,
      async json() {
        return {
          data: [
            { id: 'gpt-5.4-mini' },
            { id: 'gpt-5.5' },
          ],
        };
      },
    }),
  });

  assert.equal(result.model, 'gpt-5.5', 'auth codex should save the selected current Codex model');
  assert.deepEqual(openedUrls, [CODEX_LOGIN_URL], 'auth codex should open the ChatGPT Codex login page');
  const configText = readFileSync(join(SHARED_HOME, '.taxsentry', 'config', 'config.json'), 'utf8');
  assert.ok(configText.includes('"kind": "codex_oauth"'), 'auth codex should persist Codex OAuth provider kind');
  assert.ok(configText.includes('"model": "gpt-5.5"'), 'auth codex should persist the selected Codex model');

  mkdirSync(join(SHARED_HOME, '.codex'), { recursive: true });
  writeFileSync(join(SHARED_HOME, '.codex', 'auth.json'), JSON.stringify({
    auth_mode: 'chatgpt',
    tokens: {
      access_token: 'token-123',
      refresh_token: 'refresh-456',
      account_id: 'abc123456789',
      email: 'thienan@gmail.com',
      name: 'Thiên Ân',
    },
    last_refresh: '2026-07-01T00:00:00Z',
  }), 'utf8');

  const onboarding = await freshImport('src/onboarding.js');
  const onboardingPrompts = [
    { name: 'name', persona: 'warm, concise, and practical', language: 'vi' },
    { provider: 'codex_oauth' },
    { credentials: 'existing' },
    { selection: '1' },
    { sessionTitle: 'Sếp session', maxFacts: 20, maxTurns: 8 },
    { enabled: false },
  ];
  const onboardingConfig = await onboarding.runOnboarding({
    resetExisting: true,
    prompt: async () => onboardingPrompts.shift(),
  });

  assert.equal(
    onboardingConfig.provider.model,
    'gpt-5.5',
    'onboarding should ask whether to reuse existing Codex credentials before choosing a current Codex model',
  );

  const configModule = await freshImport('src/config.js');
  const existingConfig = configModule.getEmptyConfig();
  existingConfig.configured = true;
  existingConfig.provider = {
    kind: 'custom',
    baseUrl: 'https://api.openai.com/v1',
    model: 'gpt-4.1-mini',
    apiKey: 'secret-key',
    authMode: 'api_key',
  };
  configModule.saveConfig(existingConfig);
  configModule.writeEnvFile(existingConfig);

  const cancelPrompts = [
    { name: 'name', persona: 'warm, concise, and practical', language: 'vi' },
    { provider: 'codex_oauth' },
    { credentials: 'cancel' },
    { sessionTitle: 'Sếp session', maxFacts: 20, maxTurns: 8 },
    { enabled: false },
  ];
  const cancelledConfig = await onboarding.runOnboarding({
    resetExisting: false,
    prompt: async () => cancelPrompts.shift(),
  });

  assert.equal(
    cancelledConfig.provider.kind,
    'custom',
    'cancelling Codex OAuth onboarding should keep the existing provider kind',
  );
  assert.equal(
    cancelledConfig.provider.model,
    'gpt-4.1-mini',
    'cancelling Codex OAuth onboarding should preserve the existing provider model',
  );
} finally {
  console.log = originalLog;
  rmSync(SHARED_HOME, { recursive: true, force: true });
}
