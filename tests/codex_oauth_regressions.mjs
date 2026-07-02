import assert from 'node:assert/strict';

import { CODEX_LOGIN_URL, redactCodexAuthSummary } from '../src/utils/codex-auth.js';

assert.equal(
  CODEX_LOGIN_URL,
  'https://chatgpt.com/auth/login?next=%2Fcodex%2Fcloud',
  'Codex login URL should point to the official Google-account login flow',
);

const summary = redactCodexAuthSummary({
  authPath: 'C:\\Users\\Admin\\.codex\\auth.json',
  authMode: 'codex_oauth',
  accessToken: 'token-123',
  refreshToken: 'refresh-456',
  accountId: 'abc123456789',
  accountEmail: 'thienan@gmail.com',
  accountName: 'Thiên Ân',
  lastRefresh: '2026-07-01T00:00:00Z',
});

assert.equal(summary.accountEmail, 'th***@gmail.com', 'account email should be masked');
assert.equal(summary.accountName, 'Thiên Ân', 'account name should be preserved');
assert.equal(summary.accountId, 'abc123…', 'account id should be shortened');
