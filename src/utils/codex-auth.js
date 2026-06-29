/**
 * TaxSentry CLI - Codex OAuth utilities
 */

import { existsSync, readFileSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

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

  if (!accessToken) {
    throw new Error('Codex OAuth profile không có access token khả dụng. Hãy đăng nhập lại bằng Codex trước.');
  }

  return {
    authPath,
    authMode,
    accessToken,
    refreshToken,
    accountId,
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
    lastRefresh: auth.lastRefresh || '',
  };
}
