/**
 * TaxSentry CLI - Codex OAuth utilities
 */

import { execFileSync } from 'child_process';
import { existsSync, readFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

export const CODEX_LOGIN_URL = 'https://chatgpt.com/auth/login?next=%2Fcodex%2Fcloud';
export const CODEX_API_BASE_URL = 'https://api.openai.com/v1';
export const CODEX_RECOMMENDED_MODELS = [
  'gpt-5.5',
  'gpt-5.4',
  'gpt-5.4-mini',
  'gpt-5.3-codex-spark',
];

export function getCodexAuthPath() {
  return join(homedir(), '.codex', 'auth.json');
}

export function loadCodexAuth(authPath = getCodexAuthPath()) {
  if (!existsSync(authPath)) {
    throw new Error(`Không tìm thấy hồ sơ Codex OAuth tại ${authPath}`);
  }

  let parsed;
  try {
    parsed = JSON.parse(readFileSync(authPath, 'utf-8'));
  } catch (err) {
    throw new Error(`Không thể đọc Codex OAuth profile: ${err.message}`);
  }

  const authMode = parsed?.auth_mode || '';
  const accessToken = parsed?.tokens?.access_token || parsed?.OPENAI_API_KEY || '';
  const refreshToken = parsed?.tokens?.refresh_token || '';
  const accountId = parsed?.tokens?.account_id || '';
  const accountEmail = parsed?.tokens?.email || parsed?.user?.email || parsed?.email || '';
  const accountName = parsed?.tokens?.name || parsed?.user?.name || parsed?.name || '';

  if (!accessToken) {
    throw new Error('Codex OAuth profile không có access token khả dụng. Hãy đăng nhập lại bằng Codex trước.');
  }

  return {
    authPath,
    authMode,
    accessToken,
    refreshToken,
    accountId,
    accountEmail,
    accountName,
    lastRefresh: parsed?.last_refresh || '',
  };
}

export function redactCodexAuthSummary(auth) {
  return {
    authPath: auth.authPath,
    authMode: auth.authMode || 'unknown',
    hasAccessToken: Boolean(auth.accessToken),
    hasRefreshToken: Boolean(auth.refreshToken),
    accountId: auth.accountId ? `${String(auth.accountId).slice(0, 6)}…` : '',
    accountName: auth.accountName || '',
    accountEmail: maskEmail(auth.accountEmail || ''),
    lastRefresh: auth.lastRefresh || '',
  };
}

export function orderCodexModelIds(modelIds = []) {
  const models = uniqueStrings(modelIds);
  const recommended = CODEX_RECOMMENDED_MODELS.filter((model) => models.includes(model));
  const rest = models.filter((model) => !CODEX_RECOMMENDED_MODELS.includes(model));
  return [...recommended, ...rest];
}

export async function fetchCodexModelIds({
  auth,
  fetchImpl = globalThis.fetch,
  timeoutMs = 2500,
  limit = 24,
} = {}) {
  if (typeof fetchImpl !== 'function' || !auth?.accessToken) return [];

  let response;
  try {
    const signal = typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
      ? AbortSignal.timeout(timeoutMs)
      : undefined;
    response = await fetchImpl(`${CODEX_API_BASE_URL}/models`, {
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${auth.accessToken}`,
      },
      signal,
    });
  } catch {
    return [];
  }

  if (!response?.ok) return [];

  try {
    const payload = await response.json();
    const rawModels = Array.isArray(payload?.data)
      ? payload.data.map((item) => item?.id || item?.name || item)
      : Array.isArray(payload)
        ? payload
        : [];
    return orderCodexModelIds(rawModels).slice(0, limit);
  } catch {
    return [];
  }
}

export function openCodexLoginPage(url = CODEX_LOGIN_URL, { platform = process.platform, runner = execFileSync } = {}) {
  const candidates = platform === 'win32'
    ? [
        ['msedge', ['--inprivate', url]],
        ['chrome', ['--incognito', url]],
        ['cmd', ['/d', '/s', '/c', 'start', '', url]],
      ]
    : platform === 'darwin'
      ? [
          ['open', ['-na', 'Google Chrome', '--args', '--incognito', url]],
          ['open', ['-na', 'Microsoft Edge', '--args', '--inprivate', url]],
          ['open', [url]],
        ]
      : [
          ['google-chrome', ['--incognito', url]],
          ['chromium', ['--incognito', url]],
          ['chromium-browser', ['--incognito', url]],
          ['xdg-open', [url]],
        ];

  for (const [command, args] of candidates) {
    try {
      runner(command, args, { stdio: 'ignore' });
      return true;
    } catch {
      continue;
    }
  }

  return false;
}

function uniqueStrings(values) {
  return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))];
}

function maskEmail(value) {
  const email = String(value || '').trim();
  if (!email || !email.includes('@')) return '';

  const [local, domain] = email.split('@');
  if (!local) return `***@${domain}`;
  if (local.length <= 2) return `${local[0]}***@${domain}`;
  return `${local.slice(0, 2)}***@${domain}`;
}
