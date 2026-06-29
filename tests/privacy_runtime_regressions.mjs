import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const SHARED_HOME = mkdtempSync(join(tmpdir(), 'taxsentry-home-'));

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

async function testConfigRoundTrip() {
  const configMod = await freshImport('src/config.js');
  const { getEmptyConfig, setValue, saveConfig, writeEnvFile, loadConfig } = configMod;

  const cfg = getEmptyConfig();
  setValue(cfg, 'agent', 'name', 'TaxSentry');
  setValue(cfg, 'provider', 'kind', 'custom');
  setValue(cfg, 'provider', 'baseUrl', 'https://example.invalid/v1');
  setValue(cfg, 'provider', 'model', 'gpt-4.1-mini');
  setValue(cfg, 'provider', 'apiKey', 'SECRET_KEY_123');
  setValue(cfg, 'integrations', 'telegram', {
    enabled: true,
    botToken: 'BOT_SECRET_456',
    adminChatId: '999',
  });
  saveConfig(cfg);
  writeEnvFile(cfg);

  const configText = readFileSync(join(SHARED_HOME, '.taxsentry', 'config', 'config.json'), 'utf8');
  const envText = readFileSync(join(SHARED_HOME, '.taxsentry', 'taxsentry-core', '.env'), 'utf8');

  assert.ok(!configText.includes('SECRET_KEY_123'), 'config.json must not store provider secrets');
  assert.ok(!configText.includes('BOT_SECRET_456'), 'config.json must not store telegram secrets');
  assert.ok(envText.includes('TAXSENTRY_PROVIDER_API_KEY="SECRET_KEY_123"'), '.env must store provider secret');
  assert.ok(envText.includes('TELEGRAM_BOT_TOKEN="BOT_SECRET_456"'), '.env must store telegram secret');

  const loaded = loadConfig();
  assert.equal(loaded.provider.apiKey, 'SECRET_KEY_123', 'loadConfig should restore provider secret from .env');
  assert.equal(loaded.integrations.telegram.botToken, 'BOT_SECRET_456', 'loadConfig should restore telegram secret from .env');
}

async function testOnboardingWritesFriendlyProviderConfig() {
  const onboarding = await freshImport('src/onboarding.js');
  const promptQueue = [
    { name: 'name', persona: 'warm, concise, and practical', language: 'vi' },
    { provider: 'lmstudio' },
    { baseUrl: 'http://localhost:1234/v1', model: 'google/gemma-4-e4b' },
    { sessionTitle: 'Sếp session', maxFacts: 20, maxTurns: 8 },
    { enabled: false },
  ];
  const prompt = async () => promptQueue.shift();

  const config = await onboarding.runOnboarding({ resetExisting: true, prompt });
  assert.equal(config.provider.kind, 'lmstudio');
  assert.equal(config.provider.model, 'google/gemma-4-e4b');
  assert.equal(config.agent.language, 'vi');
  assert.equal(config.memory.maxFacts, 20);

  const envText = readFileSync(join(SHARED_HOME, '.taxsentry', 'taxsentry-core', '.env'), 'utf8');
  assert.ok(envText.includes('TAXSENTRY_PROVIDER_KIND="lmstudio"'), 'onboarding should persist provider kind');
  assert.ok(envText.includes('TAXSENTRY_PROVIDER_MODEL="google/gemma-4-e4b"'), 'onboarding should persist model');
}

await testConfigRoundTrip();
await testOnboardingWritesFriendlyProviderConfig();
rmSync(SHARED_HOME, { recursive: true, force: true });
