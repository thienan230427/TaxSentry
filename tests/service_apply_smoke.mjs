import assert from 'node:assert/strict';
import cp from 'node:child_process';
import { mkdtempSync, rmSync, readFileSync, existsSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { syncBuiltinESMExports } from 'node:module';
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

const originalPlatform = process.platform;
const originalSpawnSync = cp.spawnSync;
let linuxHome = null;

try {
  Object.defineProperty(process, 'platform', { value: 'linux' });
  cp.spawnSync = (command, args) => {
    if (command === 'systemctl' && args.includes('disable')) {
      return { status: 1, stdout: '', stderr: 'permission denied', error: null };
    }
    return { status: 0, stdout: 'ok', stderr: '', error: null };
  };
  syncBuiltinESMExports();

  linuxHome = mkdtempSync(join(tmpdir(), 'taxsentry-service-linux-'));
  process.env.HOME = linuxHome;
  process.env.USERPROFILE = linuxHome;
  process.env.HOMEDRIVE = '';
  process.env.HOMEPATH = linuxHome;
  process.env.TAXSENTRY_HOME = join(linuxHome, '.taxsentry');
  process.env.TAXSENTRY_CONFIG_FILE = join(linuxHome, '.taxsentry', 'config', 'config.json');
  process.env.TAXSENTRY_MEMORY_DB = join(linuxHome, '.taxsentry', 'memory', 'memory.db');
  process.env.TAXSENTRY_SESSION_FILE = join(linuxHome, '.taxsentry', 'memory', 'sessions.jsonl');
  process.env.TAXSENTRY_CORE_DIR = join(linuxHome, '.taxsentry', 'taxsentry-core');
  process.env.TAXSENTRY_ENV_FILE = join(linuxHome, '.taxsentry', 'taxsentry-core', '.env');

  const linuxArtifacts = await freshImport('src/utils/service-artifacts.js');
  linuxArtifacts.installServiceArtifacts(serviceName, '7150649527');
  const linuxTargetPath = linuxArtifacts.getAppliedServiceTargetPath(serviceName);
  mkdirSync(dirname(linuxTargetPath), { recursive: true });
  writeFileSync(linuxTargetPath, 'dummy', 'utf8');
  const removeResult = linuxArtifacts.removeAppliedService(serviceName);
  assert.equal(removeResult.ok, false, 'service removal should fail when the OS disable command fails');
} finally {
  cp.spawnSync = originalSpawnSync;
  syncBuiltinESMExports();
  Object.defineProperty(process, 'platform', { value: originalPlatform });
  if (linuxHome) {
    rmSync(linuxHome, { recursive: true, force: true });
  }
}

try {
  cp.execFileSync('node', [join(process.cwd(), 'bin', 'taxsentry.js'), 'service', 'stop'], {
    encoding: 'utf8',
  });
  assert.fail('service stop should exit non-zero when the OS stop command fails');
} catch (error) {
  assert.notEqual(error.status, 0, 'service stop should surface a failure exit code');
}

rmSync(SHARED_HOME, { recursive: true, force: true });
