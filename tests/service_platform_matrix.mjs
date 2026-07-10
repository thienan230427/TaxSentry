import assert from 'node:assert/strict';

import {
  getAppliedServiceNameForPlatform,
  getInstallHintLines,
  getPlatformServiceProfile,
  getServiceModuleArgs,
  getServiceProfileForPlatform,
} from '../src/utils/service-manager.ts';

const cases = [
  {
    platform: 'win32',
    normalized: 'windows',
    artifactType: 'task-scheduler',
    extension: '.xml',
    supervisor: 'Task Scheduler',
    appliedName: 'TaxSentry-telegram_bot',
    hintToken: 'schtasks /Create',
  },
  {
    platform: 'linux',
    normalized: 'linux',
    artifactType: 'systemd',
    extension: '.service',
    supervisor: 'systemd --user',
    appliedName: 'telegram_bot.service',
    hintToken: 'systemctl --user daemon-reload',
  },
  {
    platform: 'darwin',
    normalized: 'macos',
    artifactType: 'launchd',
    extension: '.plist',
    supervisor: 'launchd',
    appliedName: 'com.taxsentry.telegram_bot',
    hintToken: 'launchctl load',
  },
];

for (const testCase of cases) {
  const profile = getServiceProfileForPlatform(testCase.platform);
  assert.equal(profile.platform, testCase.normalized, `${testCase.platform} should normalize correctly`);
  assert.equal(profile.artifactType, testCase.artifactType, `${testCase.platform} artifact type should match`);
  assert.equal(profile.artifactExtension, testCase.extension, `${testCase.platform} artifact extension should match`);
  assert.equal(profile.supervisor, testCase.supervisor, `${testCase.platform} supervisor should match`);
  assert.equal(profile.installScope, 'per-user', `${testCase.platform} should be per-user scoped`);

  const appliedName = getAppliedServiceNameForPlatform(testCase.platform, 'telegram_bot');
  assert.equal(appliedName, testCase.appliedName, `${testCase.platform} applied name should match`);

  const hints = getInstallHintLines('telegram_bot', `/tmp/${testCase.platform}/artifact${testCase.extension}`, testCase.platform);
  assert.ok(hints.some((line) => line.includes(testCase.hintToken)), `${testCase.platform} install hints should include platform command`);
  assert.ok(
    getServiceModuleArgs('telegram_bot', '12345').includes('--with-automation-loop'),
    'telegram service module args should always include the automation loop flag',
  );
}

assert.equal(getPlatformServiceProfile().installScope, 'per-user', 'current platform should also be per-user scoped');

