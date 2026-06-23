import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const SHARED_HOME = mkdtempSync(join(tmpdir(), 'taxsentry-tests-'));

function applySharedHome() {
  process.env.HOME = SHARED_HOME;
  process.env.USERPROFILE = SHARED_HOME;
  process.env.HOMEDRIVE = '';
  process.env.HOMEPATH = SHARED_HOME;
}

function readRepo(relPath) {
  return readFileSync(new URL(`../${relPath}`, import.meta.url), 'utf8');
}

function testStaticGuards() {
  const envExample = readRepo('taxsentry-core/.env.example');
  assert.ok(!envExample.includes('an25800600029@hutech.edu.vn'), '.env.example must not contain personal HUTECH email');
  assert.ok(!envExample.includes('thienan12342007@gmail.com'), '.env.example must not contain personal Gmail address');

  const startJs = readRepo('src/commands/start.js');
  assert.ok(!startJs.includes('config.directorName'), 'start.js must not read deprecated flat config.directorName');

  const launcherJs = readRepo('src/launcher.js');
  assert.ok(!launcherJs.includes("env: process.env"), 'launcher startForeground must not use raw process.env');

  const installerJs = readRepo('src/installer.js');
  assert.ok(!installerJs.includes('writeFileSync(envFile, existingEnv'), 'installer must not restore previous .env silently');
  assert.ok(!installerJs.includes('existingEnv = readFileSync(envFile, \'utf-8\')'), 'installer must not preserve previous runtime .env');
  assert.ok(installerJs.includes('filter:'), 'installer copy should filter unsafe dev/runtime artifacts');

  const pdfParser = readRepo('taxsentry-core/src/taxsentry/core/pdf_parser.py');
  assert.ok(pdfParser.includes('import re'), 'pdf_parser.py must import re');
  assert.ok(!pdfParser.includes('thienan12342007@gmail.com'), 'pdf_parser.py must not hardcode developer email');
}

async function testSecretRedactionAndEnvFallback() {
  applySharedHome();

  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/config.js')).href + `?t=${Date.now()}`;
  const mod = await import(moduleUrl);
  const { getEmptyConfig, setValue, saveConfig, writeEnvFile, loadConfig, getValue } = mod;

  const cfg = getEmptyConfig();
  setValue(cfg, 'director', 'directorName', 'Security Test');
  setValue(cfg, 'telegram', 'telegramBotToken', '123456:SECRET_TOKEN');
  setValue(cfg, 'mysql', 'password', 'DB_SECRET_123');
  setValue(cfg, 'email', 'appPassword', 'APP_PASS_123');
  saveConfig(cfg);
  writeEnvFile(cfg);

  const configPath = join(SHARED_HOME, '.taxsentry', 'config', 'config.json');
  const envPath = join(SHARED_HOME, '.taxsentry', 'taxsentry-core', '.env');
  const configText = readFileSync(configPath, 'utf8');
  const envText = readFileSync(envPath, 'utf8');

  assert.ok(!configText.includes('SECRET_TOKEN'), 'config.json must not persist telegram secret');
  assert.ok(!configText.includes('DB_SECRET_123'), 'config.json must not persist DB password');
  assert.ok(!configText.includes('APP_PASS_123'), 'config.json must not persist app password');

  assert.ok(envText.includes('TELEGRAM_BOT_TOKEN=123456:SECRET_TOKEN'), '.env must retain telegram secret for runtime');
  assert.ok(envText.includes('DB_PASS=DB_SECRET_123'), '.env must retain DB password for runtime');
  assert.ok(envText.includes('EMAIL_PASS=APP_PASS_123'), '.env must retain app password for runtime');

  const loaded = loadConfig();
  assert.equal(getValue(loaded, 'telegram', 'telegramBotToken'), '123456:SECRET_TOKEN', 'secret must round-trip via .env fallback');
  assert.equal(getValue(loaded, 'mysql', 'password'), 'DB_SECRET_123', 'DB password must round-trip via .env fallback');
  assert.equal(getValue(loaded, 'email', 'appPassword'), 'APP_PASS_123', 'app password must round-trip via .env fallback');

}

async function testResetOnboardingDoesNotReuseOldSecrets() {
  applySharedHome();

  const configModuleUrl = pathToFileURL(join(process.cwd(), 'src/config.js')).href + `?t=${Date.now()}`;
  const configMod = await import(configModuleUrl);
  const { getEmptyConfig, setValue, saveConfig, writeEnvFile } = configMod;

  const existing = getEmptyConfig();
  setValue(existing, 'director', 'directorName', 'Old Director');
  setValue(existing, 'telegram', 'telegramBotToken', '111111:OLDTOKEN');
  setValue(existing, 'telegram', 'adminChatId', '12345');
  setValue(existing, 'mysql', 'password', 'OLD_DB_SECRET');
  setValue(existing, 'email', 'appPassword', 'OLD_EMAIL_SECRET');
  setValue(existing, 'email', 'accountantEmail', 'old-accountant@example.com');
  saveConfig(existing);
  writeEnvFile(existing);

  const inquirer = (await import('inquirer')).default;
  const originalPrompt = inquirer.prompt;
  const originalFetch = global.fetch;

  const answerMap = new Map([
    ['director.directorName', 'New Director'],
    ['director.directorEmail', 'director@example.com'],
    ['telegram.telegramBotToken', '222222:NEWTOKEN'],
    ['telegram.adminChatId', '99999'],
    ['mysql.host', 'localhost'],
    ['mysql.port', '3306'],
    ['mysql.user', 'root'],
    ['mysql.password', ''],
    ['mysql.database', 'tax_sentry'],
    ['email.address', 'director-login@example.com'],
    ['email.appPassword', ''],
    ['email.host', 'imap.gmail.com'],
    ['email.port', '993'],
    ['email.accountantEmail', 'accountant@example.com'],
    ['email.allowedReportSenders', ''],
  ]);

  global.fetch = async () => ({
    async json() {
      return { ok: true, result: { username: 'taxsentry_test_bot', id: 1 } };
    },
  });

  inquirer.prompt = async (questions) => {
    const list = Array.isArray(questions) ? questions : [questions];
    if (list.some((q) => q.name === 'agreed')) {
      return { agreed: true };
    }

    const answers = {};
    for (const question of list) {
      answers[question.name] = answerMap.has(question.name) ? answerMap.get(question.name) : '';
    }
    return answers;
  };

  try {
    const onboardingUrl = pathToFileURL(join(process.cwd(), 'src/onboarding.js')).href + `?t=${Date.now()}`;
    const { runOnboarding } = await import(onboardingUrl);
    await runOnboarding({ resetExisting: true });

    const envPath = join(SHARED_HOME, '.taxsentry', 'taxsentry-core', '.env');
    const envText = readFileSync(envPath, 'utf8');

    assert.ok(envText.includes('TELEGRAM_BOT_TOKEN=222222:NEWTOKEN'), 'reset setup should keep newly entered required bot token');
    assert.ok(envText.includes('DB_PASS='), 'reset setup should write DB_PASS key even when blank');
    assert.ok(envText.includes('EMAIL_PASS='), 'reset setup should write EMAIL_PASS key even when blank');
    assert.ok(!envText.includes('OLD_DB_SECRET'), 'reset setup must not silently reuse old DB password from previous .env');
    assert.ok(!envText.includes('OLD_EMAIL_SECRET'), 'reset setup must not silently reuse old email app password from previous .env');
  } finally {
    inquirer.prompt = originalPrompt;
    global.fetch = originalFetch;
    rmSync(SHARED_HOME, { recursive: true, force: true });
  }
}

async function testRunSetupFreshInstallOrchestratesResetFlow() {
  const setupUrl = pathToFileURL(join(process.cwd(), 'src/commands/setup.js')).href + `?t=${Date.now()}`;
  const { runSetup } = await import(setupUrl);

  const calls = [];
  await runSetup({
    isConfigured: () => false,
    prompt: async () => {
      throw new Error('prompt should not run on a fresh install');
    },
    detectPython: () => {
      calls.push(['detectPython']);
      return { found: true, command: 'python-test' };
    },
    printDetectionResult: (result) => {
      calls.push(['printDetectionResult', result.command]);
    },
    getInstallInstructions: () => ['install python'],
    runInstallation: async (command, forceReinstall) => {
      calls.push(['runInstallation', command, forceReinstall]);
    },
    runOnboarding: async (options) => {
      calls.push(['runOnboarding', options]);
    },
  });

  assert.deepEqual(calls, [
    ['detectPython'],
    ['printDetectionResult', 'python-test'],
    ['runInstallation', 'python-test', true],
    ['runOnboarding', { resetExisting: true }],
  ], 'runSetup should install first, then launch onboarding in reset mode');
}

async function main() {
  testStaticGuards();
  await testSecretRedactionAndEnvFallback();
  await testResetOnboardingDoesNotReuseOldSecrets();
  await testRunSetupFreshInstallOrchestratesResetFlow();
  console.log('privacy_runtime_regressions: OK');
}

main().catch((err) => {
  console.error(err.stack || err);
  process.exit(1);
});
