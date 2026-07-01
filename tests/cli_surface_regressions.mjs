import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';

const CLI = join(process.cwd(), 'bin', 'taxsentry.js');

function runHelp(args = []) {
  return execFileSync('node', [CLI, ...args, '--help'], { encoding: 'utf8' });
}

const topLevelHelp = runHelp();
assert.match(topLevelHelp, /taxsentry start/i, 'top-level help should list start');
assert.match(topLevelHelp, /taxsentry update/i, 'top-level help should list update');
assert.match(topLevelHelp, /taxsentry dashboard/i, 'top-level help should list dashboard');
assert.match(topLevelHelp, /taxsentry jobs/i, 'top-level help should list jobs');
assert.match(topLevelHelp, /taxsentry replay/i, 'top-level help should list replay');
assert.match(topLevelHelp, /taxsentry reconfigure/i, 'top-level help should list reconfigure');
assert.match(topLevelHelp, /taxsentry reset-profile/i, 'top-level help should list reset-profile');
assert.match(topLevelHelp, /taxsentry service/i, 'top-level help should list service');
assert.match(topLevelHelp, /taxsentry up/i, 'top-level help should list up');
assert.match(topLevelHelp, /taxsentry stop/i, 'top-level help should list stop');
assert.doesNotMatch(topLevelHelp, /(?:^|\n)\s*bot\s+/m, 'legacy bot alias should not be public');
assert.doesNotMatch(topLevelHelp, /(?:^|\n)\s*banner\s+/m, 'banner command should not be public');
assert.doesNotMatch(topLevelHelp, /(?:^|\n)\s*chat\s+/m, 'redundant chat alias should not be public');

const serviceHelp = runHelp(['service']);
assert.match(serviceHelp, /(?:^|\n)\s*status\s+/m, 'service help should list status');
assert.match(serviceHelp, /(?:^|\n)\s*install\s+/m, 'service help should list install');
assert.match(serviceHelp, /(?:^|\n)\s*apply\s+/m, 'service help should list apply');
assert.match(serviceHelp, /(?:^|\n)\s*start\s+/m, 'service help should list start');
assert.match(serviceHelp, /(?:^|\n)\s*stop\s+/m, 'service help should list stop');
assert.match(serviceHelp, /(?:^|\n)\s*restart\s+/m, 'service help should list restart');
assert.match(serviceHelp, /(?:^|\n)\s*remove\s+/m, 'service help should list remove');
assert.match(serviceHelp, /(?:^|\n)\s*logs\s+/m, 'service help should list logs');
assert.doesNotMatch(serviceHelp, /\buninstall\b/i, 'uninstall should not be public');

const updateHelp = runHelp(['update']);
assert.match(updateHelp, /--self/i, 'update help should show self-update flag');
assert.match(updateHelp, /--config-only/i, 'update help should show config-only flag');
assert.match(updateHelp, /--package-spec/i, 'update help should show package-spec flag');

const reconfigureHelp = runHelp(['reconfigure']);
assert.match(reconfigureHelp, /re-run onboarding/i, 'reconfigure help should explain the onboarding rerun');

const resetProfileHelp = runHelp(['reset-profile']);
assert.match(resetProfileHelp, /reset the local profile/i, 'reset-profile help should explain the full reset');

const authHelp = runHelp(['auth']);
assert.match(authHelp, /codex/i, 'auth help should expose the Codex subcommand');
