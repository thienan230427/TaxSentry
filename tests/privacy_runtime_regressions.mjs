import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
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

  const botJs = readRepo('src/commands/bot.js');
  assert.ok(!botJs.includes('taxsentry logs --service bot'), 'bot command hints must use telegram_bot service name');

  const launcherJs = readRepo('src/launcher.js');
  assert.ok(!launcherJs.includes("env: process.env"), 'launcher startForeground must not use raw process.env');
  assert.ok(launcherJs.includes('closeSync(logStream)'), 'launcher must close opened log handles after spawning');

  const upJs = readRepo('src/commands/up.js');
  assert.ok(upJs.includes("!adminChatId"), 'up.js must guard Telegram bot startup when adminChatId is missing');
  assert.ok(upJs.includes('Chỉ chạy TUI Dashboard độc lập'), 'up.js must not claim the bot is running when it is skipped');

  const pdfParser = readRepo('taxsentry-core/src/taxsentry/core/pdf_parser.py');
  assert.ok(pdfParser.includes('import re'), 'pdf_parser.py must import re');
  assert.ok(!pdfParser.includes('thienan12342007@gmail.com'), 'pdf_parser.py must not hardcode developer email');
}

async function testLaunchdStatusParserDistinguishesLoadedAndRunning() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/utils/service-artifacts.js')).href + `?t=${Date.now()}`;
  const { parseLaunchdListStatusOutput } = await import(moduleUrl);

  const label = 'com.taxsentry.telegram_bot';
  const loaded = parseLaunchdListStatusOutput(`- 0 ${label}`, label);
  assert.equal(loaded.registered, true, 'launchd loaded job must count as registered');
  assert.equal(loaded.active, false, 'launchd loaded job without PID must not count as active');

  const running = parseLaunchdListStatusOutput(`123 0 ${label}`, label);
  assert.equal(running.registered, true, 'launchd running job must count as registered');
  assert.equal(running.active, true, 'launchd job with PID must count as active');
}

async function testSecretRedactionAndEnvFallback() {
  applySharedHome();

  const pathsUrl = pathToFileURL(join(process.cwd(), 'src/utils/paths.js')).href + `?t=${Date.now()}`;
  const { CONFIG_FILE, ENV_FILE } = await import(pathsUrl);

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

  const configPath = CONFIG_FILE;
  const envPath = ENV_FILE;
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

  const pathsUrl = pathToFileURL(join(process.cwd(), 'src/utils/paths.js')).href + `?t=${Date.now()}`;
  const { TAXSENTRY_HOME, ENV_FILE } = await import(pathsUrl);

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
    ['ai.authMode', 'lmstudio'],
    ['ai.baseUrl', 'http://localhost:1234/v1'],
    ['ai.apiKey', ''],
    ['ai.modelName', 'google/gemma-4-e4b'],
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

    const envPath = ENV_FILE;
    const envText = readFileSync(envPath, 'utf8');

    assert.ok(envText.includes('TELEGRAM_BOT_TOKEN=222222:NEWTOKEN'), 'reset setup should keep newly entered required bot token');
    assert.ok(envText.includes('DB_PASS='), 'reset setup should write DB_PASS key even when blank');
    assert.ok(envText.includes('EMAIL_PASS='), 'reset setup should write EMAIL_PASS key even when blank');
    assert.ok(!envText.includes('OLD_DB_SECRET'), 'reset setup must not silently reuse old DB password from previous .env');
    assert.ok(!envText.includes('OLD_EMAIL_SECRET'), 'reset setup must not silently reuse old email app password from previous .env');
  } finally {
    inquirer.prompt = originalPrompt;
    global.fetch = originalFetch;
    rmSync(TAXSENTRY_HOME, { recursive: true, force: true });
  }
}

async function testReconfigureCanClearOptionalNonSecretFields() {
  applySharedHome();

  const pathsUrl = pathToFileURL(join(process.cwd(), 'src/utils/paths.js')).href + `?t=${Date.now()}`;
  const { ENV_FILE } = await import(pathsUrl);

  const configModuleUrl = pathToFileURL(join(process.cwd(), 'src/config.js')).href + `?t=${Date.now()}`;
  const configMod = await import(configModuleUrl);
  const { getEmptyConfig, setValue, saveConfig, writeEnvFile, loadConfig, getValue } = configMod;

  const existing = getEmptyConfig();
  setValue(existing, 'director', 'directorName', 'Old Director');
  setValue(existing, 'director', 'directorEmail', 'old-director@example.com');
  setValue(existing, 'telegram', 'telegramBotToken', '111111:OLDTOKEN');
  setValue(existing, 'telegram', 'adminChatId', '12345');
  saveConfig(existing);
  writeEnvFile(existing);

  const inquirer = (await import('inquirer')).default;
  const originalPrompt = inquirer.prompt;
  const answerMap = new Map([
    ['director.directorName', 'New Director'],
    ['director.directorEmail', ''],
    ['telegram.telegramBotToken', '111111:OLDTOKEN'],
    ['telegram.adminChatId', '12345'],
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
    ['ai.authMode', 'lmstudio'],
    ['ai.baseUrl', 'http://localhost:1234/v1'],
    ['ai.apiKey', ''],
    ['ai.modelName', 'google/gemma-4-e4b'],
  ]);

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
    await runOnboarding({ resetExisting: false });

    const loaded = loadConfig();
    assert.equal(getValue(loaded, 'director', 'directorEmail'), '', 'blank optional text field must clear during reconfigure');

    const envText = readFileSync(ENV_FILE, 'utf8');
    assert.ok(envText.includes('DIRECTOR_EMAIL='), 'reconfigure must write blank env value for cleared optional field');
  } finally {
    inquirer.prompt = originalPrompt;
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

async function testTelegramActiveReportReturnsFalseWhenPdfMissing() {
  const script = `
import asyncio
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / 'taxsentry-core' / 'src'))

calls = {'message': 0, 'document': 0}

class DummyBot:
    def __init__(self, token):
        self.token = token
    async def send_message(self, chat_id, text):
        calls['message'] += 1
        return None
    async def send_document(self, *args, **kwargs):
        calls['document'] += 1
        return None

telegram = types.ModuleType('telegram')
telegram.Bot = DummyBot
telegram.Update = object
telegram_ext = types.ModuleType('telegram.ext')
telegram_ext.Application = object
telegram_ext.CommandHandler = object
telegram_ext.ContextTypes = object
telegram_ext.MessageHandler = object
telegram_ext.filters = types.SimpleNamespace()
sys.modules['telegram'] = telegram
sys.modules['telegram.ext'] = telegram_ext

import taxsentry.bot.telegram_bot as botmod

botmod.load_evidence_context = lambda *args, **kwargs: None

async def noop(*args, **kwargs):
    return None

botmod._send_evidence_preview = noop
os.environ['TELEGRAM_BOT_TOKEN'] = '123:ABC'
os.environ['ADMIN_CHAT_ID'] = '99999'

async def main():
    result = await botmod.send_active_report_to_director('missing.pdf', 'summary text')
    print(f'RESULT={result}')
    print(f"CALLS={calls['message']}:{calls['document']}")
    assert result is False
    assert calls['message'] == 0
    assert calls['document'] == 0

asyncio.run(main())
`;

  const output = execFileSync('python', ['-c', script], {
    cwd: process.cwd(),
    encoding: 'utf8',
  });
  assert.ok(output.includes('RESULT=False'), 'Telegram active report fallback must return False without PDF attachment');
  assert.ok(output.includes('CALLS=0:0'), 'Telegram active report must not call Telegram API when PDF is missing');
}

async function testEmailSenderRequiresRecipient() {
  const script = `
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / 'taxsentry-core' / 'src'))

os.environ['EMAIL_USER'] = 'sender@example.com'
os.environ['EMAIL_PASS'] = 'VALID_APP_PASSWORD'
os.environ['DIRECTOR_EMAIL'] = ''
os.environ['DIRECTOR_NAME'] = 'Giám đốc'

from taxsentry.core.email_sender import TaxSentryEmailSender

sender = TaxSentryEmailSender()
assert sender.is_configured() is False
assert sender.send_report('missing.pdf') is False
print('RESULT=OK')
`;

  const output = execFileSync('python', ['-c', script], {
    cwd: process.cwd(),
    encoding: 'utf8',
  });
  assert.ok(output.includes('RESULT=OK'), 'email sender must refuse to run without DIRECTOR_EMAIL');
}

async function testProcessedIdsPersistWithoutArbitraryCap() {
  const script = `
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / 'taxsentry-core' / 'src'))

from taxsentry.core.email_poller import TaxSentryEmailPoller

poller = TaxSentryEmailPoller()
poller.processed_ids = {str(i) for i in range(600)}
poller._save_processed_ids()

payload = json.loads(poller.processed_file.read_text(encoding='utf-8'))
assert len(payload['ids']) == 600
poller.processed_file.unlink(missing_ok=True)
print('RESULT=OK')
`;

  const output = execFileSync('python', ['-c', script], {
    cwd: process.cwd(),
    encoding: 'utf8',
  });
  assert.ok(output.includes('RESULT=OK'), 'processed_ids persistence must not truncate arbitrarily');
}

async function testAutomationStopsWhenDatabaseSyncFails() {
  const script = `
import os
import sys
import types
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path.cwd() / 'taxsentry-core' / 'src'))

pdfplumber = types.ModuleType('pdfplumber')
sys.modules['pdfplumber'] = pdfplumber

reportlab = types.ModuleType('reportlab')
reportlab_lib = types.ModuleType('reportlab.lib')
reportlab_lib_pagesizes = types.ModuleType('reportlab.lib.pagesizes')
reportlab_lib_pagesizes.letter = (612, 792)
reportlab_pdfbase = types.ModuleType('reportlab.pdfbase')
reportlab_pdfbase.pdfmetrics = types.SimpleNamespace(registerFont=lambda *args, **kwargs: None)
reportlab_pdfbase_ttfonts = types.ModuleType('reportlab.pdfbase.ttfonts')
reportlab_pdfbase_ttfonts.TTFont = lambda *args, **kwargs: None
reportlab_platypus = types.ModuleType('reportlab.platypus')
for name in ['SimpleDocTemplate', 'Paragraph', 'Spacer', 'Table', 'TableStyle', 'PageBreak', 'HRFlowable']:
    setattr(reportlab_platypus, name, type(name, (), {}))
reportlab_styles = types.ModuleType('reportlab.lib.styles')
reportlab_styles.getSampleStyleSheet = lambda: {}
reportlab_styles.ParagraphStyle = lambda *args, **kwargs: None
reportlab_colors = types.ModuleType('reportlab.lib.colors')
reportlab_enums = types.ModuleType('reportlab.lib.enums')
reportlab_enums.TA_CENTER = 0
reportlab_enums.TA_LEFT = 0
reportlab_enums.TA_JUSTIFY = 0

sys.modules['reportlab'] = reportlab
sys.modules['reportlab.lib'] = reportlab_lib
sys.modules['reportlab.lib.pagesizes'] = reportlab_lib_pagesizes
sys.modules['reportlab.pdfbase'] = reportlab_pdfbase
sys.modules['reportlab.pdfbase.ttfonts'] = reportlab_pdfbase_ttfonts
sys.modules['reportlab.platypus'] = reportlab_platypus
sys.modules['reportlab.lib.styles'] = reportlab_styles
sys.modules['reportlab.lib.colors'] = reportlab_colors
sys.modules['reportlab.lib.enums'] = reportlab_enums

import taxsentry.core.automation as automation
import taxsentry.bot.telegram_bot as botmod

class FakeParser:
    def __init__(self, path):
        self.path = path
    def load(self):
        return None
    def parse_assumptions(self):
        return None
    def parse_income_statement(self):
        return None
    def has_meaningful_data(self):
        return True
    def export_json(self, output_path):
        Path(output_path).write_text('{"ok": true}', encoding='utf-8')
    def log_to_database(self):
        return False

class FakeGenerator:
    def __init__(self):
        pass
    def generate(self, markdown, output_path):
        Path(output_path).write_text(markdown, encoding='utf-8')
        return True

automation.TaxSentryParser = FakeParser
automation.TaxSentryPDFGenerator = FakeGenerator
automation.build_evidence_context = lambda parser, file_context: {'image_attachments': []}
automation.save_evidence_context = lambda *args, **kwargs: None

workflow = automation.TaxSentryAutomationWorkflow()
workflow.poller.connect = lambda: True
workflow.poller.disconnect = lambda: None
workflow.poller.check_and_download = lambda: [str(Path('dummy.xlsx'))]
workflow.poller.get_file_context = lambda path: {'email_id': 'email-1'}
workflow.poller.mark_as_processed = mock.Mock()
workflow.engine.run_audit = mock.Mock(return_value='# report')
workflow.generator.generate = mock.Mock(return_value=True)
workflow.sender.send_report = mock.Mock(return_value=True)

tel = mock.AsyncMock(return_value=True)
botmod.send_active_report_to_director = tel

result = workflow.run_once()
print(f'RESULT={result}')
print(f'RUN_AUDIT={workflow.engine.run_audit.call_count}')
print(f'SEND_REPORT={workflow.sender.send_report.call_count}')
print(f'TELEGRAM={tel.await_count}')
print(f'MARK={workflow.poller.mark_as_processed.call_count}')
assert result == 0
assert workflow.engine.run_audit.call_count == 0
assert workflow.sender.send_report.call_count == 0
assert tel.await_count == 0
assert workflow.poller.mark_as_processed.call_count == 0
print('RESULT=OK')
`;

  const output = execFileSync('python', ['-c', script], {
    cwd: process.cwd(),
    encoding: 'utf8',
  });
  assert.ok(output.includes('RESULT=OK'), 'automation must stop after database sync failure');
  assert.ok(output.includes('RUN_AUDIT=0'), 'database sync failure must not continue to AI audit');
  assert.ok(output.includes('SEND_REPORT=0'), 'database sync failure must not send email');
  assert.ok(output.includes('TELEGRAM=0'), 'database sync failure must not send telegram');
  assert.ok(output.includes('MARK=0'), 'database sync failure must not mark processed');
}

async function testServiceManagerSupportsAllPlatformProfiles() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/utils/service-manager.js')).href + `?t=${Date.now()}`;
  const {
    getServiceProfileForPlatform,
    getAppliedServiceNameForPlatform,
  } = await import(moduleUrl);

  assert.deepEqual(getServiceProfileForPlatform('win32'), {
    platform: 'windows',
    manager: 'local-process',
    supervisor: 'Task Scheduler',
    detached: true,
    gracefulSignal: 'SIGTERM',
    forceSignal: 'SIGKILL',
    artifactType: 'task-scheduler',
    artifactExtension: '.xml',
    installScope: 'per-user',
    notes: 'Hiện dùng PID file + child process local; có thể nâng cấp sang Task Scheduler.',
  });

  assert.deepEqual(getServiceProfileForPlatform('linux'), {
    platform: 'linux',
    manager: 'local-process',
    supervisor: 'systemd --user',
    detached: true,
    gracefulSignal: 'SIGTERM',
    forceSignal: 'SIGKILL',
    artifactType: 'systemd',
    artifactExtension: '.service',
    installScope: 'per-user',
    notes: 'Hiện dùng PID file + child process local; phù hợp để nâng cấp sang systemd user service.',
  });

  assert.deepEqual(getServiceProfileForPlatform('darwin'), {
    platform: 'macos',
    manager: 'local-process',
    supervisor: 'launchd',
    detached: true,
    gracefulSignal: 'SIGTERM',
    forceSignal: 'SIGKILL',
    artifactType: 'launchd',
    artifactExtension: '.plist',
    installScope: 'per-user',
    notes: 'Hiện dùng PID file + child process local; phù hợp để nâng cấp sang launchd agent.',
  });

  assert.equal(getAppliedServiceNameForPlatform('win32', 'telegram_bot'), 'TaxSentry-telegram_bot');
  assert.equal(getAppliedServiceNameForPlatform('linux', 'telegram_bot'), 'telegram_bot.service');
  assert.equal(getAppliedServiceNameForPlatform('darwin', 'telegram_bot'), 'com.taxsentry.telegram_bot');
}

async function testDoctorSummaryGroupsIssuesForFastTriage() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/doctor.js')).href + `?t=${Date.now()}`;
  const { buildDoctorSummary } = await import(moduleUrl);

  const summary = buildDoctorSummary({
    healthy: false,
    issues: [
      'Cấu hình cơ bản: Thiếu config.json hoặc .env.',
      'Telegram runtime: Thiếu token hoặc Admin Chat ID.',
      'Email sender: Thiếu EMAIL_USER / EMAIL_PASS / DIRECTOR_EMAIL.',
      'PDFPlumber import: Thiếu module Python: pdfplumber.',
      'Telegram Bot service: Chưa chạy. Artifact hiện tại: D:/fake/taxsentry.log',
    ],
  });

  assert.equal(summary.blockingCount, 5);
  assert.deepEqual(summary.issueBuckets, {
    config: 1,
    runtime: 1,
    email: 1,
    dependency: 1,
    service: 1,
  });
  assert.deepEqual(summary.topIssues, [
    'Cấu hình cơ bản: Thiếu config.json hoặc .env.',
    'Telegram runtime: Thiếu token hoặc Admin Chat ID.',
    'Email sender: Thiếu EMAIL_USER / EMAIL_PASS / DIRECTOR_EMAIL.',
  ]);
}

async function testDoctorTroubleshootingGuideIsActionable() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/doctor.js')).href + `?t=${Date.now()}`;
  const { buildDoctorTroubleshootingGuide } = await import(moduleUrl);

  const guide = buildDoctorTroubleshootingGuide({
    issues: [
      'Cấu hình cơ bản: Thiếu config.json hoặc .env.',
      'Telegram runtime: Thiếu token hoặc Admin Chat ID.',
      'Email sender: Thiếu EMAIL_USER / EMAIL_PASS / DIRECTOR_EMAIL.',
      'Email poller: Thiếu EMAIL_USER / EMAIL_PASS / ACCOUNTANT_EMAIL.',
      'PDFPlumber import: Thiếu module Python: pdfplumber.',
      'Telegram Bot service: Chưa chạy. Artifact hiện tại: D:/fake/taxsentry.log',
    ],
  });

  assert.deepEqual(guide.map((item) => item.category), ['config', 'telegram', 'email', 'imap', 'dependency:pdfplumber', 'service']);
  assert.ok(guide[0].action.includes('taxsentry setup'));
  assert.ok(guide[1].action.includes('telegram.telegramBotToken'));
  assert.ok(guide[2].action.includes('email.address'));
  assert.ok(guide[3].action.includes('ACCOUNTANT_EMAIL'));
  assert.ok(guide[4].action.includes('pdfplumber'));
  assert.ok(guide[5].action.includes('taxsentry doctor'));
}

async function testDoctorTroubleshootingGuideCoversRuntimeBuckets() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/doctor.js')).href + `?t=${Date.now()}`;
  const { buildDoctorTroubleshootingGuide } = await import(moduleUrl);

  const guide = buildDoctorTroubleshootingGuide({
    issues: [
      'Python 3.10+: Không tìm thấy Python hợp lệ trên hệ thống.',
      'Director profile: Thiếu DIRECTOR_NAME.',
      'MySQL runtime: Thiếu DB_HOST / DB_USER / DB_PASS / DB_NAME.',
    ],
  });

  assert.deepEqual(guide.map((item) => item.category), ['runtime:python', 'runtime:director', 'runtime:mysql']);
  assert.ok(guide[0].action.includes('Python 3.10+'));
  assert.ok(guide[1].action.includes('director.directorName'));
  assert.ok(guide[2].action.includes('mysql.host'));
}

async function testDoctorReportHighlightsMissingRuntimeRequirements() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/doctor.js')).href + `?t=${Date.now()}`;
  const { collectDoctorReport } = await import(moduleUrl);

  const config = {
    director: { directorName: 'Sếp', directorEmail: '' },
    telegram: { telegramBotToken: '123:ABC', adminChatId: '' },
    email: { address: 'sender@example.com', appPassword: 'APP_PASS', accountantEmail: '' },
    mysql: { host: 'localhost', user: 'root', password: '', database: 'tax_sentry' },
  };

  const report = collectDoctorReport({
    detectPythonFn: () => ({ found: true, command: 'python', version: { major: 3, minor: 11, patch: 8 } }),
    isConfiguredFn: () => true,
    loadConfigFn: () => config,
    getValueFn: (cfg, group, key) => cfg[group]?.[key] ?? '',
    getPlatformNameFn: () => 'Windows',
    getServiceStatusFn: () => ({ running: false, pids: [], logFile: 'D:/fake/taxsentry.log' }),
    getServiceAdapterFn: () => ({ runtimeMode: 'local-process', recommendedSupervisor: 'Task Scheduler' }),
    getServiceProfileForPlatformFn: () => ({ platform: 'windows', artifactType: 'task-scheduler' }),
    probeCoreDependenciesFn: () => [
      { key: 'dep-pandas', label: 'Pandas import', ok: true, detail: 'pandas importable.' },
      { key: 'dep-pdfplumber', label: 'PDFPlumber import', ok: false, detail: 'Thiếu module Python: pdfplumber.' },
    ],
  });

  assert.equal(report.healthy, false);
  assert.ok(report.issues.some((issue) => issue.includes('Telegram runtime')));
  assert.ok(report.issues.some((issue) => issue.includes('Email sender')));
  assert.ok(report.issues.some((issue) => issue.includes('Email poller')));
  assert.ok(report.issues.some((issue) => issue.includes('MySQL runtime')));
  assert.ok(report.issues.some((issue) => issue.includes('Telegram Bot service')));
  assert.ok(report.issues.some((issue) => issue.includes('PDFPlumber import')));
  assert.equal(report.coreDependencies.length, 2);
}

async function testReconfigureCommandUsesExistingConfigWithoutReset() {

  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/reconfigure.js')).href + `?t=${Date.now()}`;
  const { runReconfigure } = await import(moduleUrl);

  const calls = [];
  await runReconfigure({
    isConfigured: () => true,
    runOnboarding: async (options) => {
      calls.push(options);
    },
  });

  assert.deepEqual(calls, [{ resetExisting: false }]);
}

async function testResetProfileCommandForcesCleanReinstall() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/reset-profile.js')).href + `?t=${Date.now()}`;
  const { runResetProfile } = await import(moduleUrl);

  const calls = [];
  await runResetProfile({
    isConfigured: () => true,
    prompt: async () => ({ confirmReset: true }),
    detectPython: () => {
      calls.push(['detectPython']);
      return { found: true, command: 'python-reset' };
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
    ['printDetectionResult', 'python-reset'],
    ['runInstallation', 'python-reset', true],
    ['runOnboarding', { resetExisting: true }],
  ], 'reset-profile should reinstall then launch onboarding in reset mode');
}

async function testStartCommandUsesForegroundLauncher() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/start.js')).href + `?t=${Date.now()}`;
  const { default: startCommand } = await import(moduleUrl);

  const calls = [];
  await startCommand({
    getDirectorNameFn: () => 'Sếp',
    startForegroundFn: (args) => {
      calls.push(['startForeground', args]);
      return 0;
    },
  });

  assert.deepEqual(calls, [
    ['startForeground', ['-m', 'taxsentry']],
  ], 'start command should launch the foreground Python entrypoint');
}

async function testBotCommandUsesBackgroundLauncher() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/bot.js')).href + `?t=${Date.now()}`;
  const { default: botCommand } = await import(moduleUrl);

  const calls = [];
  const config = {
    director: { directorName: 'Sếp' },
    telegram: { telegramBotToken: '123:ABC', adminChatId: '99999' },
  };

  await botCommand({
    loadConfigFn: () => config,
    getValueFn: (cfg, group, key) => cfg[group]?.[key] ?? '',
    isRunningFn: () => false,
    getPidFn: () => null,
    getServiceAdapterFn: () => {
      calls.push(['getServiceAdapter']);
      return { runtimeMode: 'local-process', recommendedSupervisor: 'Task Scheduler' };
    },
    getServiceModuleArgsFn: (serviceName, adminChatId) => {
      calls.push(['getServiceModuleArgs', serviceName, adminChatId]);
      return ['-m', 'taxsentry.bot.telegram_bot', adminChatId];
    },
    startBackgroundFn: (serviceName, args) => {
      calls.push(['startBackground', serviceName, args]);
      return 4321;
    },
  });

  assert.deepEqual(calls, [
    ['getServiceModuleArgs', 'telegram_bot', '99999'],
    ['getServiceAdapter'],
    ['startBackground', 'telegram_bot', ['-m', 'taxsentry.bot.telegram_bot', '99999']],
  ], 'bot command should launch the Telegram bot through the background launcher');
}

async function testUpCommandOrchestratesAttachedBotAndForegroundTui() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/up.js')).href + `?t=${Date.now()}`;
  const { default: upCommand } = await import(moduleUrl);

  const calls = [];
  const child = {
    pid: 5678,
    exitCode: null,
    kill: (signal) => {
      calls.push(['kill', signal]);
    },
  };
  const config = {
    isConfigured: true,
    director: { directorName: 'Sếp' },
    telegram: { telegramBotToken: '123:ABC', adminChatId: '99999' },
  };

  await upCommand({
    loadConfigFn: () => config,
    getValueFn: (cfg, group, key) => cfg[group]?.[key] ?? '',
    isRunningFn: () => false,
    getServiceModuleArgsFn: (serviceName, adminChatId) => {
      calls.push(['getServiceModuleArgs', serviceName, adminChatId]);
      return ['-m', 'taxsentry.bot.telegram_bot', adminChatId];
    },
    startAttachedFn: (serviceName, args) => {
      calls.push(['startAttached', serviceName, args]);
      return child;
    },
    startForegroundFn: (args) => {
      calls.push(['startForeground', args]);
      return 0;
    },
    stopServiceFn: (serviceName) => {
      calls.push(['stopService', serviceName]);
    },
    sleepFn: async (ms) => {
      calls.push(['sleep', ms]);
    },
  });

  assert.deepEqual(calls, [
    ['getServiceModuleArgs', 'telegram_bot', '99999'],
    ['startAttached', 'telegram_bot', ['-m', 'taxsentry.bot.telegram_bot', '99999']],
    ['sleep', 2000],
    ['startForeground', ['-m', 'taxsentry']],
    ['stopService', 'telegram_bot'],
    ['kill', 'SIGTERM'],
  ], 'up command should attach the bot, run foreground TUI, then clean up');
}

async function testAuthCodexCommandConfiguresOauthModeWithoutPersistingToken() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/auth-codex.js')).href + `?t=${Date.now()}`;
  const { runAuthCodex } = await import(moduleUrl);
  const configModuleUrl = pathToFileURL(join(process.cwd(), 'src/config.js')).href + `?t=${Date.now()}`;
  const { getEmptyConfig, getValue } = await import(configModuleUrl);

  const config = getEmptyConfig();
  let wroteEnv = false;

  await runAuthCodex({
    loadConfigFn: () => config,
    saveConfigFn: () => {},
    writeEnvFileFn: () => {
      wroteEnv = true;
    },
    loadCodexAuthFn: () => ({
      authPath: '/fake/.codex/auth.json',
      authMode: 'chatgpt',
      accessToken: 'tok_123',
      refreshToken: 'ref_456',
      accountId: 'acct_7890',
      lastRefresh: '2026-06-29T10:00:00Z',
    }),
  });

  assert.equal(getValue(config, 'ai', 'authMode'), 'codex_oauth');
  assert.equal(getValue(config, 'ai', 'baseUrl'), 'https://api.openai.com/v1');
  assert.equal(getValue(config, 'ai', 'apiKey'), '');
  assert.ok(wroteEnv, 'auth codex must regenerate .env after changing auth mode');
}

async function testUpdateCommandAbortsOnDirtyGitTree() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/update.js')).href + `?t=${Date.now()}`;
  const { runUpdate } = await import(moduleUrl);

  await assert.rejects(
    () => runUpdate({
      projectRoot: 'D:/fake/TaxSentry',
      packageJson: { repository: { url: 'https://github.com/thienan230427/TaxSentry.git' } },
      isGitCheckoutFn: () => true,
      getGitStatusFn: () => ' M src/index.js',
      detectPythonFn: () => ({ found: true, command: 'python' }),
      printDetectionResultFn: () => {},
      refreshInstalledRuntimeFn: async () => {},
    }),
    /Working tree hiện đang bẩn/
  );
}

async function testUpdateCommandFastForwardsCleanGitCheckoutAndRefreshesRuntime() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/update.js')).href + `?t=${Date.now()}`;
  const { runUpdate } = await import(moduleUrl);

  const calls = [];
  await runUpdate({
    projectRoot: 'D:/fake/TaxSentry',
    packageJson: { repository: { url: 'https://github.com/thienan230427/TaxSentry.git' } },
    isGitCheckoutFn: () => true,
    getGitStatusFn: () => '',
    getCurrentBranchFn: () => 'main',
    getRemoteUrlFn: () => 'https://github.com/thienan230427/TaxSentry.git',
    runGitFn: (args) => {
      calls.push(['git', args]);
      return '';
    },
    detectPythonFn: () => ({ found: true, command: 'python-upd' }),
    printDetectionResultFn: (result) => {
      calls.push(['printDetectionResult', result.command]);
    },
    refreshInstalledRuntimeFn: async (command) => {
      calls.push(['refreshInstalledRuntime', command]);
    },
  });

  assert.deepEqual(calls, [
    ['git', ['fetch', 'origin', 'main']],
    ['git', ['pull', '--ff-only', 'origin', 'main']],
    ['printDetectionResult', 'python-upd'],
    ['refreshInstalledRuntime', 'python-upd'],
  ]);
}

async function testUpdateCommandUsesStagingCopyWhenGitMetadataMissing() {
  const moduleUrl = pathToFileURL(join(process.cwd(), 'src/commands/update.js')).href + `?t=${Date.now()}`;
  const { runUpdate } = await import(moduleUrl);

  const calls = [];
  await runUpdate({
    projectRoot: 'D:/fake/package-root',
    packageJson: { repository: { url: 'https://github.com/thienan230427/TaxSentry.git' } },
    isGitCheckoutFn: () => false,
    prepareStageFn: (repoUrl, branch) => {
      calls.push(['prepareStage', repoUrl, branch]);
      return 'D:/fake/stage';
    },
    replaceManagedPathsFn: (stageRoot, currentProjectRoot) => {
      calls.push(['replaceManagedPaths', stageRoot, currentProjectRoot]);
    },
    detectPythonFn: () => ({ found: true, command: 'python-stage' }),
    printDetectionResultFn: (result) => {
      calls.push(['printDetectionResult', result.command]);
    },
    refreshInstalledRuntimeFn: async (command) => {
      calls.push(['refreshInstalledRuntime', command]);
    },
  });

  assert.deepEqual(calls, [
    ['prepareStage', 'https://github.com/thienan230427/TaxSentry.git', 'main'],
    ['replaceManagedPaths', 'D:/fake/stage', 'D:/fake/package-root'],
    ['printDetectionResult', 'python-stage'],
    ['refreshInstalledRuntime', 'python-stage'],
  ]);
}

async function main() {
  testStaticGuards();
  await testSecretRedactionAndEnvFallback();
  await testResetOnboardingDoesNotReuseOldSecrets();
  await testReconfigureCanClearOptionalNonSecretFields();
  await testRunSetupFreshInstallOrchestratesResetFlow();
  await testReconfigureCommandUsesExistingConfigWithoutReset();
  await testResetProfileCommandForcesCleanReinstall();
  await testStartCommandUsesForegroundLauncher();
  await testBotCommandUsesBackgroundLauncher();
  await testUpCommandOrchestratesAttachedBotAndForegroundTui();
  await testAuthCodexCommandConfiguresOauthModeWithoutPersistingToken();
  await testUpdateCommandAbortsOnDirtyGitTree();
  await testUpdateCommandFastForwardsCleanGitCheckoutAndRefreshesRuntime();
  await testUpdateCommandUsesStagingCopyWhenGitMetadataMissing();
  await testEmailSenderRequiresRecipient();
  await testProcessedIdsPersistWithoutArbitraryCap();
  await testTelegramActiveReportReturnsFalseWhenPdfMissing();
  await testAutomationStopsWhenDatabaseSyncFails();
  await testLaunchdStatusParserDistinguishesLoadedAndRunning();
  await testServiceManagerSupportsAllPlatformProfiles();
  await testDoctorSummaryGroupsIssuesForFastTriage();
  await testDoctorTroubleshootingGuideIsActionable();
  await testDoctorTroubleshootingGuideCoversRuntimeBuckets();
  await testDoctorReportHighlightsMissingRuntimeRequirements();

}

main().catch((err) => {
  console.error(err.stack || err);
  process.exit(1);
});
