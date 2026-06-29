import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, rmSync } from 'node:fs';
import { join } from 'node:path';

function packTarball() {
  const npmCli = process.env.npm_execpath;
  assert.ok(npmCli, 'npm_execpath must be set when running under npm');
  const output = execFileSync(process.execPath, [npmCli, 'pack', '--ignore-scripts', '--json', '--silent'], {
    cwd: process.cwd(),
    encoding: 'utf8',
    env: {
      ...process.env,
      npm_config_dry_run: 'false',
    },
  }).trim();
  const packed = JSON.parse(output);
  assert.equal(Array.isArray(packed), true, 'npm pack should return a JSON array');
  assert.equal(packed.length, 1, 'npm pack should produce exactly one tarball');
  return packed[0].filename;
}

function inspectTarball(tarballPath) {
  const script = `import json, sys, tarfile\npath = sys.argv[1]\nwith tarfile.open(path, 'r:gz') as tar:\n    names = tar.getnames()\n    env = tar.extractfile('package/taxsentry-core/.env.example').read().decode('utf-8')\nprint(json.dumps({'names': names, 'env': env}))`;
  const output = execFileSync('python', ['-c', script, tarballPath], { encoding: 'utf8' }).trim();
  return JSON.parse(output);
}

function assertHas(names, entry) {
  assert.ok(names.includes(entry), `tarball must include ${entry}`);
}

function assertNoMatch(names, predicate, message) {
  assert.ok(!names.some(predicate), message);
}

const tarballName = packTarball();
const tarballPath = join(process.cwd(), tarballName);

try {
  assert.ok(existsSync(tarballPath), 'npm pack should write the tarball to disk');
  const { names, env } = inspectTarball(tarballPath);

  assertHas(names, 'package/package.json');
  assertHas(names, 'package/README.md');
  assertHas(names, 'package/bin/taxsentry.js');
  assertHas(names, 'package/src/config.js');
  assertHas(names, 'package/src/onboarding.js');
  assertHas(names, 'package/taxsentry-core/.env.example');
  assertHas(names, 'package/taxsentry-core/pyproject.toml');
  assertHas(names, 'package/taxsentry-core/requirements.txt');
  assertHas(names, 'package/taxsentry-core/src/taxsentry/app.py');
  assertHas(names, 'package/taxsentry-core/src/taxsentry/providers.py');
  assertHas(names, 'package/taxsentry-core/src/taxsentry/memory.py');

  assertNoMatch(names, (entry) => entry.startsWith('package/tests/'), 'tarball must not contain repository tests');
  assertNoMatch(names, (entry) => entry.startsWith('package/docs/'), 'tarball must not contain docs/');
  assertNoMatch(names, (entry) => entry.includes('/.env') && entry !== 'package/taxsentry-core/.env.example', 'tarball must not contain secret env files');
  assertNoMatch(names, (entry) => entry.endsWith('.db'), 'tarball must not contain database files');
  assertNoMatch(names, (entry) => entry.includes('node_modules'), 'tarball must not contain node_modules');

  assert.ok(env.includes('TAXSENTRY_PROVIDER_KIND='), '.env.example should include provider kind');
  assert.ok(env.includes('TAXSENTRY_PROVIDER_URL='), '.env.example should include provider URL');
  assert.ok(env.includes('TAXSENTRY_PROVIDER_MODEL='), '.env.example should include provider model');
  assert.ok(env.includes('TAXSENTRY_PROVIDER_API_KEY='), '.env.example should include provider API key placeholder');
  assert.ok(env.includes('TAXSENTRY_MEMORY_DB='), '.env.example should include memory DB path');

  await import('../src/commands/setup.js');
  await import('../src/commands/start.js');
} finally {
  if (existsSync(tarballPath)) rmSync(tarballPath, { force: true });
}
