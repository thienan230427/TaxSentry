/**
 * TaxSentry CLI - Codex OAuth utilities
 */

import { execFileSync } from 'child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

export const CODEX_LOGIN_URL = 'https://chatgpt.com/auth/login?next=%2Fcodex%2Fcloud';
export const CODEX_DEVICE_LOGIN_URL = 'https://auth.openai.com/codex/device';
export const CODEX_DEVICE_CLIENT_ID = 'app_EMoamEEZ73f0CkXaXp7hrann';
export const CODEX_DEVICE_USERCODE_URL = 'https://auth.openai.com/api/accounts/deviceauth/usercode';
export const CODEX_DEVICE_TOKEN_URL = 'https://auth.openai.com/api/accounts/deviceauth/token';
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

export async function requestCodexDeviceCode({
  fetchImpl = globalThis.fetch,
  clientId = CODEX_DEVICE_CLIENT_ID,
} = {}) {
  if (typeof fetchImpl !== 'function') {
    throw new Error('Trình chạy không hỗ trợ fetch để xin mã đăng nhập Codex.');
  }

  const response = await fetchImpl(CODEX_DEVICE_USERCODE_URL, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ client_id: clientId }),
  });

  const payload = await readJsonResponse(response, 'mã đăng nhập Codex');
  const deviceAuthId = String(payload?.device_auth_id || payload?.deviceAuthId || '').trim();
  const userCode = String(payload?.user_code || payload?.userCode || '').trim();
  if (!deviceAuthId || !userCode) {
    throw new Error('Codex device login không trả về đủ deviceAuthId hoặc userCode.');
  }

  return {
    deviceAuthId,
    userCode,
    intervalMs: toIntervalMs(payload?.interval || payload?.interval_seconds || payload?.intervalSeconds),
    expiresAt: String(payload?.expires_at || payload?.expiresAt || '').trim(),
    verificationUrl: String(
      payload?.verification_url
      || payload?.verification_uri
      || payload?.verification_uri_complete
      || CODEX_DEVICE_LOGIN_URL,
    ).trim() || CODEX_DEVICE_LOGIN_URL,
    raw: payload,
  };
}

export async function pollCodexDeviceAuth({
  fetchImpl = globalThis.fetch,
  clientId = CODEX_DEVICE_CLIENT_ID,
  deviceAuthId,
  userCode,
  intervalMs = 5000,
  timeoutMs = 15 * 60 * 1000,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
} = {}) {
  if (typeof fetchImpl !== 'function') {
    throw new Error('Trình chạy không hỗ trợ fetch để xác nhận đăng nhập Codex.');
  }
  if (!deviceAuthId || !userCode) {
    throw new Error('Thiếu deviceAuthId hoặc userCode để xác nhận đăng nhập Codex.');
  }

  const startedAt = Date.now();
  let lastError = null;

  while ((Date.now() - startedAt) < timeoutMs) {
    const response = await fetchImpl(CODEX_DEVICE_TOKEN_URL, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        client_id: clientId,
        device_auth_id: deviceAuthId,
        user_code: userCode,
      }),
    });

    const payload = await readJsonResponse(response, 'xác nhận đăng nhập Codex', { allowPending: true });
    const normalized = normalizeCodexAuthPayload(payload);
    if (normalized) {
      await saveCodexAuth(normalized);
      return normalized;
    }

    const errorCode = String(payload?.error?.code || payload?.code || '').trim();
    if (errorCode && !PENDING_DEVICE_AUTH_ERRORS.has(errorCode)) {
      throw new Error(payload?.error?.message || payload?.message || `Codex device auth failed: ${errorCode}`);
    }

    if (!response.ok && !errorCode) {
      lastError = new Error(`Codex device auth failed with status ${response.status}`);
    }

    await sleep(intervalMs);
  }

  if (lastError) {
    throw lastError;
  }

  throw new Error('Codex device auth timed out. Hãy thử đăng nhập lại.');
}

export function codexAuthFingerprint(auth = null) {
  if (!auth) return '';

  return [
    auth.authMode || '',
    auth.accountId || '',
    auth.accountEmail || '',
    auth.accountName || '',
    auth.lastRefresh || '',
    auth.accessToken ? 'access' : '',
    auth.refreshToken ? 'refresh' : '',
  ].join('|');
}

export async function waitForCodexAuthChange({
  loadAuth = loadCodexAuth,
  previousFingerprint = '',
  timeoutMs = 15 * 60 * 1000,
  pollIntervalMs = 1000,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
} = {}) {
  const startedAt = Date.now();
  let lastError = null;

  while ((Date.now() - startedAt) < timeoutMs) {
    try {
      const auth = loadAuth();
      if (auth && codexAuthFingerprint(auth) !== previousFingerprint) {
        return auth;
      }
    } catch (error) {
      lastError = error;
    }

    await sleep(pollIntervalMs);
  }

  if (!previousFingerprint) {
    try {
      return loadAuth();
    } catch (error) {
      lastError = error;
    }
  }

  if (lastError) {
    throw lastError;
  }

  return null;
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

export async function saveCodexAuth(auth, authPath = getCodexAuthPath()) {
  const normalized = {
    auth_mode: auth?.authMode || 'codex_oauth',
    tokens: {
      access_token: auth?.accessToken || '',
      refresh_token: auth?.refreshToken || '',
      account_id: auth?.accountId || '',
      email: auth?.accountEmail || '',
      name: auth?.accountName || '',
    },
    last_refresh: auth?.lastRefresh || new Date().toISOString(),
  };

  mkdirSync(join(authPath, '..'), { recursive: true });
  writeFileSync(authPath, `${JSON.stringify(normalized, null, 2)}\n`, 'utf-8');
  return authPath;
}

async function readJsonResponse(response, context, { allowPending = false } = {}) {
  if (!response?.ok && !(allowPending && response?.status === 403)) {
    throw new Error(`Codex ${context} failed with status ${response?.status ?? 'unknown'}`);
  }

  try {
    return await response.json();
  } catch (error) {
    throw new Error(`Không thể đọc phản hồi ${context}: ${error.message}`);
  }
}

function normalizeCodexAuthPayload(payload) {
  const accessToken = String(
    payload?.access_token
    || payload?.accessToken
    || payload?.tokens?.access_token
    || payload?.tokens?.accessToken
    || '',
  ).trim();

  if (!accessToken) return null;

  return {
    authPath: getCodexAuthPath(),
    authMode: String(payload?.auth_mode || payload?.authMode || 'codex_oauth'),
    accessToken,
    refreshToken: String(
      payload?.refresh_token
      || payload?.refreshToken
      || payload?.tokens?.refresh_token
      || payload?.tokens?.refreshToken
      || '',
    ).trim(),
    accountId: String(payload?.account_id || payload?.accountId || payload?.tokens?.account_id || payload?.tokens?.accountId || '').trim(),
    accountEmail: String(payload?.email || payload?.account_email || payload?.accountEmail || payload?.tokens?.email || '').trim(),
    accountName: String(payload?.name || payload?.account_name || payload?.accountName || payload?.tokens?.name || '').trim(),
    lastRefresh: new Date().toISOString(),
  };
}

function toIntervalMs(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds <= 0) return 5000;
  return Math.max(1000, Math.round(seconds * 1000));
}

const PENDING_DEVICE_AUTH_ERRORS = new Set([
  'deviceauth_authorization_pending',
  'authorization_pending',
  'slow_down',
]);

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
