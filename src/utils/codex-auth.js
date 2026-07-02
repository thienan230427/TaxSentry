/**
 * TaxSentry CLI - Codex OAuth utilities
 */

import { execFileSync } from 'child_process';
import { existsSync, readFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

export const CODEX_LOGIN_URL = 'https://chatgpt.com/auth/login?next=%2Fcodex%2Fcloud';

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

export function openCodexLoginPage(url = CODEX_LOGIN_URL) {
  const platform = process.platform;
  const command = platform === 'win32' ? 'cmd' : platform === 'darwin' ? 'open' : 'xdg-open';
  const args = platform === 'win32'
    ? ['/c', 'start', '', url]
    : [url];

  try {
    execFileSync(command, args, { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

function maskEmail(value) {
  const email = String(value || '').trim();
  if (!email || !email.includes('@')) return '';

  const [local, domain] = email.split('@');
  if (!local) return `***@${domain}`;
  if (local.length <= 2) return `${local[0]}***@${domain}`;
  return `${local.slice(0, 2)}***@${domain}`;
}
