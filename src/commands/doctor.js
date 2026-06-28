/**
 * 🛡️ TaxSentry CLI - Doctor Command
 * Deep diagnostics for runtime readiness, config gaps, and service semantics.
 */

import { spawnSync } from 'child_process';
import chalk from 'chalk';
import { detectPython } from '../utils/python-detector.js';
import { isConfigured, loadConfig, getValue } from '../config.js';
import { getPlatformName } from '../utils/paths.js';
import { getServiceAdapter, getServiceProfileForPlatform } from '../utils/service-manager.js';
import { getServiceStatus } from '../launcher.js';

const CORE_DEPENDENCIES = [
  { key: 'pandas', label: 'Pandas', importName: 'pandas', packageName: 'pandas' },
  { key: 'openpyxl', label: 'OpenPyXL', importName: 'openpyxl', packageName: 'openpyxl' },
  { key: 'pdfplumber', label: 'PDFPlumber', importName: 'pdfplumber', packageName: 'pdfplumber' },
  { key: 'reportlab', label: 'ReportLab', importName: 'reportlab', packageName: 'reportlab' },
  { key: 'openai', label: 'OpenAI client', importName: 'openai', packageName: 'openai' },
  { key: 'telegram', label: 'Python-Telegram-Bot', importName: 'telegram', packageName: 'python-telegram-bot' },
  { key: 'pymysql', label: 'PyMySQL', importName: 'pymysql', packageName: 'pymysql' },
  { key: 'rich', label: 'Rich', importName: 'rich', packageName: 'rich' },
];

function normalizeText(value) {
  if (value === undefined || value === null) return '';
  return String(value).trim();
}

function isNonEmpty(value) {
  return normalizeText(value) !== '';
}

function findCoreDependencyByIssue(issue) {
  const text = normalizeText(issue).toLowerCase();
  return CORE_DEPENDENCIES.find((item) => {
    const tokens = [item.key, item.label, item.importName, item.packageName]
      .filter(Boolean)
      .map((token) => token.toLowerCase());
    return tokens.some((token) => text.includes(token));
  }) || null;
}

function classifyDoctorIssue(issue) {
  const text = normalizeText(issue).toLowerCase();

  if (text.includes('telegram bot service')) return 'service';
  if (text.includes('email sender') || text.includes('email poller')) return 'email';
  if (text.includes('pdfplumber') || text.includes('pandas') || text.includes('openpyxl') || text.includes('reportlab') || text.includes('openai') || text.includes('python-telegram-bot') || text.includes('pymysql') || text.includes('rich')) {
    return 'dependency';
  }
  if (text.includes('telegram runtime') || text.includes('mysql runtime') || text.includes('python 3.10+') || text.includes('director profile')) {
    return 'runtime';
  }
  if (text.includes('cấu hình cơ bản') || text.includes('config') || text.includes('thiếu config')) {
    return 'config';
  }
  return 'other';
}

function classifyDoctorTroubleshootingCategory(issue) {
  const text = normalizeText(issue).toLowerCase();

  if (text.includes('cấu hình cơ bản') || text.includes('config') || text.includes('thiếu config')) return 'config';
  if (text.includes('telegram bot service')) return 'service';
  if (text.includes('python 3.10+')) return 'runtime:python';
  if (text.includes('director profile')) return 'runtime:director';
  if (text.includes('mysql runtime')) return 'runtime:mysql';
  if (text.includes('telegram runtime')) return 'telegram';
  if (text.includes('email sender')) return 'email';
  if (text.includes('email poller')) return 'imap';
  const dependency = findCoreDependencyByIssue(text);
  if (dependency) {
    return `dependency:${dependency.key}`;
  }
  return 'other';
}

function buildTroubleshootingAction(category) {
  if (category.startsWith('dependency:')) {
    const dependencyKey = category.slice('dependency:'.length);
    const dependency = CORE_DEPENDENCIES.find((item) => item.key === dependencyKey);
    if (dependency) {
      return `Cài module Python còn thiếu: \`${dependency.packageName}\` (import: \`${dependency.importName}\`), rồi chạy lại \`npm run test\` và \`taxsentry doctor\`.`;
    }
  }

  switch (category) {
    case 'config':
      return 'Chạy `taxsentry setup` hoặc `taxsentry reconfigure` để tạo lại config.json/.env rồi kiểm tra lại bằng `taxsentry doctor`.';
    case 'runtime:python':
      return 'Cài hoặc trỏ tới Python 3.10+ hợp lệ, rồi chạy lại `taxsentry doctor` để xác nhận interpreter đúng.';
    case 'runtime:director':
      return 'Kiểm tra `director.directorName` và `director.directorEmail`, rồi chạy lại `taxsentry doctor`.';
    case 'runtime:mysql':
      return 'Kiểm tra `mysql.host`, `mysql.user`, `mysql.password`, và `mysql.database`, sau đó chạy lại `taxsentry doctor` hoặc kiểm tra kết nối DB.';
    case 'telegram':
      return 'Kiểm tra `telegram.telegramBotToken` và `telegram.adminChatId`, sau đó chạy lại `taxsentry doctor` hoặc `taxsentry up`.';
    case 'email':
      return 'Kiểm tra `email.address`, `email.appPassword`, và `director.directorEmail` để xác thực SMTP sender.';
    case 'imap':
      return 'Kiểm tra `email.address`, `email.appPassword`, và `ACCOUNTANT_EMAIL` / `email.accountantEmail` để xác thực IMAP poller.';
    case 'service':
      return 'Xem log bằng `taxsentry logs --service telegram_bot`, rồi chạy lại `taxsentry doctor` và khởi động lại bằng `taxsentry up` nếu service chưa chạy.';
    default:
      return 'Kiểm tra lại cấu hình liên quan rồi chạy `taxsentry doctor` để thu hẹp nguyên nhân.';
  }
}

export function buildDoctorSummary(report) {
  const issues = Array.isArray(report?.issues) ? report.issues : [];
  const issueBuckets = issues.reduce((acc, issue) => {
    const bucket = classifyDoctorIssue(issue);
    if (bucket !== 'other') {
      acc[bucket] = (acc[bucket] || 0) + 1;
    }
    return acc;
  }, {});

  return {
    healthy: Boolean(report?.healthy),
    blockingCount: issues.length,
    issueBuckets,
    topIssues: issues.slice(0, 3),
  };
}

export function buildDoctorTroubleshootingGuide(report) {
  const issues = Array.isArray(report?.issues) ? report.issues : [];
  const guide = [];
  const seen = new Set();

  for (const issue of issues) {
    const category = classifyDoctorTroubleshootingCategory(issue);
    if (category === 'other' || seen.has(category)) {
      continue;
    }

    seen.add(category);
    guide.push({
      category,
      issue,
      action: buildTroubleshootingAction(category),
    });
  }

  return guide;
}

function splitCommand(command) {
  return normalizeText(command).split(/\s+/).filter(Boolean);
}

function probeCoreDependencies(pythonCommand) {
  const parts = splitCommand(pythonCommand);
  if (parts.length === 0) {
    return [];
  }

  const [executable, ...args] = parts;
  const script = [
    'import importlib, json, sys',
    `modules = ${JSON.stringify(CORE_DEPENDENCIES.map((item) => item.importName))}`,
    'missing = []',
    'for name in modules:',
    '    try:',
    '        importlib.import_module(name)',
    '    except Exception:',
    '        missing.append(name)',
    'print(json.dumps({"missing": missing}))',
    'sys.exit(0 if not missing else 1)',
  ].join('\n');

  const result = spawnSync(executable, [...args, '-c', script], {
    encoding: 'utf-8',
    timeout: 10000,
  });

  const output = String(result.stdout || result.stderr || '').trim();
  let missing = [];

  try {
    const parsed = output ? JSON.parse(output) : { missing: [] };
    missing = Array.isArray(parsed.missing) ? parsed.missing : [];
  } catch {
    missing = CORE_DEPENDENCIES.map((item) => item.importName);
  }

  return CORE_DEPENDENCIES.map((item) => {
    const ok = !missing.includes(item.importName);
    return {
      key: `dep-${item.key}`,
      label: `${item.label} import`,
      ok,
      detail: ok
        ? `${item.importName} importable.`
        : `Thiếu module Python: ${item.importName}.`,
    };
  });
}

export function collectDoctorReport(deps = {}) {
  const detectPythonFn = deps.detectPythonFn ?? detectPython;
  const isConfiguredFn = deps.isConfiguredFn ?? isConfigured;
  const loadConfigFn = deps.loadConfigFn ?? loadConfig;
  const getValueFn = deps.getValueFn ?? getValue;
  const getPlatformNameFn = deps.getPlatformNameFn ?? getPlatformName;
  const getServiceStatusFn = deps.getServiceStatusFn ?? getServiceStatus;
  const getServiceAdapterFn = deps.getServiceAdapterFn ?? getServiceAdapter;
  const getServiceProfileForPlatformFn = deps.getServiceProfileForPlatformFn ?? getServiceProfileForPlatform;
  const probeCoreDependenciesFn = deps.probeCoreDependenciesFn ?? probeCoreDependencies;

  const config = loadConfigFn();
  const python = detectPythonFn();
  const platform = getPlatformNameFn();
  const serviceStatus = getServiceStatusFn('telegram_bot');
  const serviceAdapter = getServiceAdapterFn('telegram_bot');
  const platformProfile = getServiceProfileForPlatformFn(process.platform);
  const coreDependencies = python?.found ? probeCoreDependenciesFn(python.command) : [];

  const telegramBotToken = normalizeText(getValueFn(config, 'telegram', 'telegramBotToken'));
  const adminChatId = normalizeText(getValueFn(config, 'telegram', 'adminChatId'));
  const directorName = normalizeText(getValueFn(config, 'director', 'directorName'));
  const directorEmail = normalizeText(getValueFn(config, 'director', 'directorEmail'));
  const accountantEmail = normalizeText(getValueFn(config, 'email', 'accountantEmail'));
  const emailUser = normalizeText(getValueFn(config, 'email', 'address'));
  const emailPass = normalizeText(getValueFn(config, 'email', 'appPassword'));
  const dbHost = normalizeText(getValueFn(config, 'mysql', 'host'));
  const dbUser = normalizeText(getValueFn(config, 'mysql', 'user'));
  const dbPass = normalizeText(getValueFn(config, 'mysql', 'password'));
  const dbName = normalizeText(getValueFn(config, 'mysql', 'database'));

  const checks = [
    {
      key: 'python',
      label: 'Python 3.10+',
      ok: Boolean(python?.found),
      detail: python?.found
        ? `${python.command} (${python.version.major}.${python.version.minor}.${python.version.patch})`
        : 'Không tìm thấy Python hợp lệ trên hệ thống.',
    },
    {
      key: 'config',
      label: 'Cấu hình cơ bản',
      ok: isConfiguredFn(),
      detail: isConfiguredFn() ? 'config.json + .env đã tồn tại.' : 'Thiếu config.json hoặc .env.',
    },
    {
      key: 'director',
      label: 'Director profile',
      ok: isNonEmpty(directorName),
      detail: isNonEmpty(directorName)
        ? `Đã nhận diện giám đốc: ${directorName}.`
        : 'Thiếu DIRECTOR_NAME.',
    },
    {
      key: 'telegram-config',
      label: 'Telegram runtime',
      ok: isNonEmpty(telegramBotToken) && isNonEmpty(adminChatId),
      detail: isNonEmpty(telegramBotToken) && isNonEmpty(adminChatId)
        ? 'Token và Admin Chat ID đã sẵn sàng.'
        : 'Thiếu token hoặc Admin Chat ID.',
    },
    {
      key: 'email-sender',
      label: 'Email sender',
      ok: isNonEmpty(emailUser) && isNonEmpty(emailPass) && isNonEmpty(directorEmail),
      detail: isNonEmpty(emailUser) && isNonEmpty(emailPass) && isNonEmpty(directorEmail)
        ? 'SMTP sender đã sẵn sàng.'
        : 'Thiếu EMAIL_USER / EMAIL_PASS / DIRECTOR_EMAIL.',
    },
    {
      key: 'email-poller',
      label: 'Email poller',
      ok: isNonEmpty(emailUser) && isNonEmpty(emailPass) && isNonEmpty(accountantEmail),
      detail: isNonEmpty(emailUser) && isNonEmpty(emailPass) && isNonEmpty(accountantEmail)
        ? 'IMAP poller đã sẵn sàng.'
        : 'Thiếu EMAIL_USER / EMAIL_PASS / ACCOUNTANT_EMAIL.',
    },
    {
      key: 'mysql',
      label: 'MySQL runtime',
      ok: isNonEmpty(dbHost) && isNonEmpty(dbUser) && isNonEmpty(dbPass) && isNonEmpty(dbName),
      detail: isNonEmpty(dbHost) && isNonEmpty(dbUser) && isNonEmpty(dbPass) && isNonEmpty(dbName)
        ? 'DB host/user/password/database đầy đủ.'
        : 'Thiếu DB_HOST / DB_USER / DB_PASS / DB_NAME.',
    },
    {
      key: 'service',
      label: 'Telegram Bot service',
      ok: Boolean(serviceStatus?.running),
      detail: serviceStatus?.running
        ? `Đang chạy với PID(s): ${serviceStatus.pids.join(', ')}`
        : `Chưa chạy. Artifact hiện tại: ${serviceStatus?.logFile || 'n/a'}`,
    },
  ];

  const issues = [
    ...checks.filter((check) => !check.ok).map((check) => `${check.label}: ${check.detail}`),
    ...coreDependencies.filter((check) => !check.ok).map((check) => `${check.label}: ${check.detail}`),
  ];

  return {
    platform,
    platformProfile,
    serviceAdapter,
    configured: isConfiguredFn(),
    python,
    checks,
    coreDependencies,
    issues,
    healthy: issues.length === 0,
  };
}

export function printDoctorReport(report) {
  const summary = buildDoctorSummary(report);
  const troubleshootingGuide = buildDoctorTroubleshootingGuide(report);

  console.log(chalk.bold.cyan('\n🩺 TaxSentry Doctor\n'));
  console.log(chalk.dim(`   Platform: ${report.platform}`));
  console.log(chalk.dim(`   Service adapter: ${report.serviceAdapter.runtimeMode} / ${report.serviceAdapter.recommendedSupervisor}`));
  console.log(chalk.dim(`   Platform profile: ${report.platformProfile.platform} / ${report.platformProfile.artifactType}`));
  console.log();

  for (const check of report.checks) {
    const mark = check.ok ? chalk.green('OK') : chalk.red('FAIL');
    const detailStyle = check.ok ? chalk.green : chalk.yellow;
    console.log(`${mark} ${check.label}`);
    console.log(detailStyle(`   ${check.detail}`));
  }

  if (report.coreDependencies?.length) {
    console.log();
    console.log(chalk.bold('Core dependency healthchecks:'));
    for (const check of report.coreDependencies) {
      const mark = check.ok ? chalk.green('OK') : chalk.red('FAIL');
      const detailStyle = check.ok ? chalk.green : chalk.yellow;
      console.log(`${mark} ${check.label}`);
      console.log(detailStyle(`   ${check.detail}`));
    }
  }

  console.log();
  if (report.healthy) {
    console.log(chalk.green('✅ Doctor summary: hệ thống trông ổn, không phát hiện lỗi cấu hình/runtime lớn.'));
  } else {
    const bucketParts = Object.entries(summary.issueBuckets)
      .filter(([, count]) => count > 0)
      .map(([bucket, count]) => `${bucket}:${count}`);

    console.log(chalk.yellow(`⚠️ Doctor summary: ${summary.blockingCount} vấn đề cần xử lý.`));
    if (bucketParts.length > 0) {
      console.log(chalk.dim(`   Buckets: ${bucketParts.join(' · ')}`));
    }
    if (summary.topIssues.length > 0) {
      console.log(chalk.bold('   Top issues:'));
    }
    for (const issue of summary.topIssues) {
      console.log(chalk.yellow(`   - ${issue}`));
    }

    if (troubleshootingGuide.length > 0) {
      console.log();
      console.log(chalk.bold('   Troubleshooting hints:'));
      for (const item of troubleshootingGuide) {
        console.log(chalk.cyan(`   • [${item.category}] ${item.action}`));
      }
    }
  }

  console.log();
}

export default async function doctorCommand(deps = {}) {
  const report = collectDoctorReport(deps);
  printDoctorReport(report);
  return report;
}
