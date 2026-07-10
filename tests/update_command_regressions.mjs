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

const { getEmptyConfig, saveConfig, writeEnvFile } = await freshImport('src/config.ts');
const updateModule = await freshImport('src/commands/update.ts');

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
  npmCliPath: 'C:/fake/npm-cli.js',
  runner: (...args) => {
    runnerInvocations.push(args);
  },
});

assert.equal(runnerInvocations.length, 1, 'runSelfUpdate should invoke the runner exactly once');
assert.equal(runnerInvocations[0][0], process.execPath);
assert.deepEqual(runnerInvocations[0][1], [
  'C:/fake/npm-cli.js',
  'install',
  '-g',
  'taxsentry@latest',
]);
assert.equal(runnerInvocations[0][2].stdio, 'inherit');

const resolvedNpmCliPath = updateModule.resolveNpmCliPath();
assert.ok(typeof resolvedNpmCliPath === 'string' && resolvedNpmCliPath.length > 0, 'resolveNpmCliPath should find an npm CLI path on this machine');
assert.ok(resolvedNpmCliPath.endsWith('npm-cli.js'), 'resolveNpmCliPath should point to npm-cli.js');

const brokenHome = mkdtempSync(join(tmpdir(), 'taxsentry-launcher-'));
process.env.HOME = brokenHome;
process.env.USERPROFILE = brokenHome;
process.env.HOMEDRIVE = '';
process.env.HOMEPATH = brokenHome;
process.env.TAXSENTRY_HOME = join(brokenHome, '.taxsentry');
process.env.TAXSENTRY_CONFIG_FILE = join(brokenHome, '.taxsentry', 'config', 'config.json');
process.env.TAXSENTRY_MEMORY_DB = join(brokenHome, '.taxsentry', 'memory', 'memory.db');
process.env.TAXSENTRY_SESSION_FILE = join(brokenHome, '.taxsentry', 'memory', 'sessions.jsonl');
process.env.TAXSENTRY_CORE_DIR = join(brokenHome, '.taxsentry', 'taxsentry-core');
process.env.TAXSENTRY_ENV_FILE = join(brokenHome, '.taxsentry', 'taxsentry-core', '.env');

const launcher = await freshImport('src/launcher.ts');
assert.equal(
  launcher.startForeground(['status']),
  1,
  'startForeground should return a non-zero exit code when Python cannot be spawned',
);
assert.equal(
  launcher.startBackground(['tui']),
  null,
  'startBackground should return null when Python cannot be spawned',
);

const upModule = await freshImport('src/commands/up.ts');
process.exitCode = 0;
await upModule.default();
assert.equal(process.exitCode, 1, 'up should set a non-zero exit code when the runtime is missing');
process.exitCode = 0;

const envText = readFileSync(join(SHARED_HOME, '.taxsentry', 'taxsentry-core', '.env'), 'utf8');
assert.ok(envText.includes('TAXSENTRY_PROVIDER_KIND="lmstudio"'), 'update should preserve provider env values');

rmSync(SHARED_HOME, { recursive: true, force: true });

