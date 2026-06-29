import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(__dirname, '..');

function packTarball() {
  const command = process.platform === 'win32' ? 'cmd' : 'npm';
  const args = process.platform === 'win32'
    ? ['/d', '/s', '/c', 'npm pack --ignore-scripts --json --silent']
    : ['pack', '--ignore-scripts', '--json', '--silent'];

  const output = execFileSync(command, args, {
    cwd: REPO_ROOT,
    encoding: 'utf8',
  }).trim();

  const packed = JSON.parse(output);
  assert.ok(Array.isArray(packed) && packed.length === 1, 'npm pack should produce exactly one tarball');
  assert.ok(packed[0]?.filename, 'npm pack must return a tarball filename');
  return packed[0].filename;
}

function inspectTarball(tarballPath) {
  const pythonScript = `import json, sys, tarfile\npath = sys.argv[1]\nwith tarfile.open(path, 'r:gz') as tar:\n    names = tar.getnames()\n    try:\n        env = tar.extractfile('package/taxsentry-core/.env.example').read().decode('utf-8')\n    except Exception:\n        env = ''\nprint(json.dumps({'names': names, 'env': env}))`;

  const output = execFileSync('python', ['-c', pythonScript, tarballPath], {
    encoding: 'utf8',
  }).trim();

  return JSON.parse(output);
}

function assertHas(names, entry) {
  assert.ok(names.includes(entry), `packed tarball must include ${entry}`);
}

function assertNoMatch(names, predicate, message) {
  assert.ok(!names.some(predicate), message);
}

async function main() {
  const tarballName = packTarball();
  const tarballPath = join(REPO_ROOT, tarballName);

  try {
    assert.ok(existsSync(tarballPath), 'npm pack must write a tarball to disk');
    const { names, env } = inspectTarball(tarballPath);

    assertHas(names, 'package/package.json');
    assertHas(names, 'package/README.md');
    assertHas(names, 'package/LICENSE');
    assertHas(names, 'package/bin/taxsentry.js');
    assertHas(names, 'package/src/commands/doctor.js');
    assertHas(names, 'package/taxsentry-core/pyproject.toml');
    assertHas(names, 'package/taxsentry-core/requirements.txt');
    assertHas(names, 'package/taxsentry-core/.env.example');
    assertHas(names, 'package/taxsentry-core/tests/test_excel_parser_regressions.py');

    assertNoMatch(names, (entry) => entry.startsWith('package/docs/'), 'tarball must not contain docs/');
    assertNoMatch(names, (entry) => entry.startsWith('package/tests/'), 'tarball must not contain repo test harness files');
    assertNoMatch(names, (entry) => entry.startsWith('package/node_modules/'), 'tarball must not contain node_modules/');
    assertNoMatch(names, (entry) => entry.includes('/.env') && entry !== 'package/taxsentry-core/.env.example', 'tarball must not contain secret env files');
    assertNoMatch(names, (entry) => entry.includes('audit_report.md'), 'tarball must not contain audit_report.md');
    assertNoMatch(names, (entry) => entry.includes('dogfood-report.md'), 'tarball must not contain dogfood-report.md');
    assertNoMatch(names, (entry) => entry.includes('worklog-'), 'tarball must not contain worklog artifacts');
    assertNoMatch(names, (entry) => entry.includes('.processed_ids.json'), 'tarball must not contain processed-id cache files');
    assertNoMatch(names, (entry) => entry.includes('parsed_report.json'), 'tarball must not contain parsed report artifacts');
    assertNoMatch(names, (entry) => entry.endsWith('.db'), 'tarball must not contain database files');
    assertNoMatch(names, (entry) => entry.includes('/scratch/'), 'tarball must not contain scratch directories');
    assertNoMatch(names, (entry) => entry.includes('/downloads/'), 'tarball must not contain download directories');

    assert.ok(!env.includes('an25800600029@hutech.edu.vn'), 'tarball .env.example must not include personal HUTECH email');
    assert.ok(!env.includes('loancao954@gmail.com'), 'tarball .env.example must not include personal Gmail address');
    assert.ok(env.includes('EMAIL_PASS='), 'tarball .env.example must include placeholder EMAIL_PASS');
    assert.ok(env.includes('ACCOUNTANT_EMAIL='), 'tarball .env.example must include ACCOUNTANT_EMAIL');
    assert.ok(env.includes('DB_PASS='), 'tarball .env.example must include placeholder DB_PASS');
  } finally {
    if (existsSync(tarballPath)) {
      rmSync(tarballPath, { force: true });
    }
  }
}

main().catch((err) => {
  console.error(err.stack || err);
  process.exit(1);
});
