import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const SHARED_HOME = mkdtempSync(join(tmpdir(), 'taxsentry-service-'));

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

const configMod = await freshImport('src/config.js');
const artifactsMod = await freshImport('src/utils/service-artifacts.js');

const cfg = configMod.getEmptyConfig();
cfg.integrations.telegram.adminChatId = '7150649527';
configMod.saveConfig(cfg);
configMod.writeEnvFile(cfg);

const serviceName = 'telegram_bot';
const artifactPath = artifactsMod.getServiceArtifactPath(serviceName);
const targetPath = artifactsMod.getAppliedServiceTargetPath(serviceName);

const installResult = artifactsMod.installServiceArtifacts(serviceName, '7150649527');
assert.equal(installResult.artifactPath, artifactPath);
assert.ok(existsSync(artifactPath), 'service artifact should be written in temp home');

const commandLog = [];
const applyResult = artifactsMod.applyServiceDefinition(serviceName, '7150649527', {
  runCommand: (command, args) => {
    commandLog.push([command, args]);
    return { status: 0, stdout: 'ok', stderr: '', error: null };
  },
});

assert.equal(applyResult.ok, true, 'service apply should succeed with a mocked runner');
assert.equal(applyResult.action, 'register');
assert.equal(applyResult.appliedName.includes('telegram_bot'), true);
assert.ok(commandLog.length >= 1, 'service apply should invoke at least one command');
assert.ok(commandLog.every(([command]) => ['schtasks', 'systemctl', 'launchctl'].includes(command)), 'service apply should only call service manager commands');

if (applyResult.targetPath) {
  assert.equal(applyResult.targetPath, targetPath);
  assert.ok(existsSync(applyResult.targetPath), 'service apply should copy the artifact to the target path');
  assert.equal(readFileSync(applyResult.targetPath, 'utf8').length > 0, true);
}

rmSync(SHARED_HOME, { recursive: true, force: true });
