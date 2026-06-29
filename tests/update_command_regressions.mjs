import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const SHARED_HOME = mkdtempSync(join(tmpdir(), 'taxsentry-update-'));

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
  const fileUrl = pathToFileURL(join(process.cwd(), relPath)).href;
  return import(`${fileUrl}?t=${Date.now()}-${Math.random()}`);
}

applySharedHome();

const { getEmptyConfig, saveConfig, writeEnvFile } = await freshImport('src/config.js');
const updateModule = await freshImport('src/commands/update.js');

const seedConfig = getEmptyConfig();
seedConfig.agent.name = 'TaxSentry';
seedConfig.provider.kind = 'lmstudio';
seedConfig.provider.baseUrl = 'http://localhost:1234/v1';
seedConfig.provider.model = 'google/gemma-4-e4b';
saveConfig(seedConfig);
writeEnvFile(seedConfig);

const calls = {
  selfUpdate: 0,
  refresh: 0,
  selfUpdateOptions: null,
};

await updateModule.default({
  self: true,
  packageSpec: 'taxsentry@latest',
  runSelfUpdate: async ({ packageSpec }) => {
    calls.selfUpdate += 1;
    assert.equal(packageSpec, 'taxsentry@latest');
  },
  refreshRuntimeConfig: async () => {
    calls.refresh += 1;
    return seedConfig;
  },
});

assert.equal(calls.selfUpdate, 1, 'update should trigger a self-update when requested');
assert.equal(calls.refresh, 1, 'update should refresh runtime config after self-update');

const runnerInvocations = [];
await updateModule.runSelfUpdate({
  packageSpec: 'taxsentry@latest',
  runner: (...args) => {
    runnerInvocations.push(args);
  },
});

assert.equal(runnerInvocations.length, 1, 'runSelfUpdate should invoke the runner exactly once');
assert.equal(runnerInvocations[0][0], 'npm');
assert.deepEqual(runnerInvocations[0][1], ['install', '-g', 'taxsentry@latest']);
assert.equal(runnerInvocations[0][2].stdio, 'inherit');
assert.equal(runnerInvocations[0][2].shell, process.platform === 'win32');

const envText = readFileSync(join(SHARED_HOME, '.taxsentry', 'taxsentry-core', '.env'), 'utf8');
assert.ok(envText.includes('TAXSENTRY_PROVIDER_KIND="lmstudio"'), 'update should preserve provider env values');

rmSync(SHARED_HOME, { recursive: true, force: true });
