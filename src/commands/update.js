/**
 * TaxSentry CLI - self-update command
 */

import { execFileSync } from 'child_process';
import { cpSync, existsSync, mkdtempSync, mkdirSync, readFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import chalk from 'chalk';
import { detectPython, printDetectionResult, getInstallInstructions } from '../utils/python-detector.js';
import { refreshInstalledRuntime } from '../installer.js';
import { info, success, error, warn } from '../utils/logger.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PROJECT_ROOT = join(__dirname, '..', '..');
const MANAGED_PATHS = ['bin', 'src', 'taxsentry-core', 'package.json', 'README.md', 'LICENSE'];
const DEFAULT_REPOSITORY_URL = 'https://github.com/thienan230427/TaxSentry.git';

function runCommand(command, args, cwd) {
  return execFileSync(command, args, {
    cwd,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
}

function parseRepositoryUrl(packageJson) {
  const repository = packageJson?.repository;
  if (!repository) return '';
  if (typeof repository === 'string') return repository;
  if (typeof repository === 'object' && repository.url) return repository.url;
  return '';
}

export function replaceManagedPathsFromStage(stageRoot, targetRoot, deps = {}) {
  const existsSyncFn = deps.existsSyncFn ?? existsSync;
  const mkdirSyncFn = deps.mkdirSyncFn ?? mkdirSync;
  const rmSyncFn = deps.rmSyncFn ?? rmSync;
  const cpSyncFn = deps.cpSyncFn ?? cpSync;
  const mkdtempSyncFn = deps.mkdtempSyncFn ?? mkdtempSync;
  const backupRoot = mkdtempSyncFn(join(tmpdir(), 'taxsentry-update-backup-'));
  const touched = [];

  try {
    mkdirSyncFn(backupRoot, { recursive: true });

    for (const relPath of MANAGED_PATHS) {
      const sourcePath = join(stageRoot, relPath);
      const targetPath = join(targetRoot, relPath);
      const backupPath = join(backupRoot, relPath);

      if (!existsSyncFn(sourcePath)) {
        throw new Error(`Staging source thiếu path bắt buộc: ${relPath}`);
      }

      if (existsSyncFn(targetPath)) {
        mkdirSyncFn(dirname(backupPath), { recursive: true });
        cpSyncFn(targetPath, backupPath, { recursive: true });
      }

      rmSyncFn(targetPath, { recursive: true, force: true });
      mkdirSyncFn(dirname(targetPath), { recursive: true });
      cpSyncFn(sourcePath, targetPath, { recursive: true });
      touched.push(relPath);
    }

    return { backupRoot, touched };
  } catch (err) {
    for (const relPath of touched.reverse()) {
      const targetPath = join(targetRoot, relPath);
      const backupPath = join(backupRoot, relPath);
      rmSyncFn(targetPath, { recursive: true, force: true });
      if (existsSyncFn(backupPath)) {
        mkdirSyncFn(dirname(targetPath), { recursive: true });
        cpSyncFn(backupPath, targetPath, { recursive: true });
      }
    }
    throw err;
  } finally {
    rmSyncFn(backupRoot, { recursive: true, force: true });
  }
}

export async function runUpdate(deps = {}) {
  const projectRoot = deps.projectRoot ?? PROJECT_ROOT;
  const isGitCheckoutFn = deps.isGitCheckoutFn ?? ((root) => existsSync(join(root, '.git')));
  const getGitStatusFn = deps.getGitStatusFn ?? ((root) => runCommand('git', ['status', '--porcelain'], root));
  const getCurrentBranchFn = deps.getCurrentBranchFn ?? ((root) => runCommand('git', ['branch', '--show-current'], root) || 'main');
  const getRemoteUrlFn = deps.getRemoteUrlFn ?? ((root) => runCommand('git', ['remote', 'get-url', 'origin'], root));
  const runGitFn = deps.runGitFn ?? ((args, cwd) => runCommand('git', args, cwd));
  const prepareStageFn = deps.prepareStageFn ?? ((repoUrl, branch) => {
    const stageRoot = mkdtempSync(join(tmpdir(), 'taxsentry-update-stage-'));
    runGitFn(['clone', '--depth', '1', '--branch', branch, repoUrl, stageRoot], projectRoot);
    return stageRoot;
  });
  const replaceManagedPathsFn = deps.replaceManagedPathsFn ?? replaceManagedPathsFromStage;
  const detectPythonFn = deps.detectPythonFn ?? detectPython;
  const printDetectionResultFn = deps.printDetectionResultFn ?? printDetectionResult;
  const getInstallInstructionsFn = deps.getInstallInstructionsFn ?? getInstallInstructions;
  const refreshInstalledRuntimeFn = deps.refreshInstalledRuntimeFn ?? refreshInstalledRuntime;
  const packageJson = deps.packageJson ?? JSON.parse(readFileSync(join(projectRoot, 'package.json'), 'utf-8'));
  const derivedRepositoryUrl = parseRepositoryUrl(packageJson) || (isGitCheckoutFn(projectRoot) ? getRemoteUrlFn(projectRoot) : '') || DEFAULT_REPOSITORY_URL;
  const repositoryUrl = deps.repositoryUrl ?? derivedRepositoryUrl;

  info('Đang kiểm tra điều kiện để cập nhật TaxSentry...');

  if (isGitCheckoutFn(projectRoot)) {
    const dirtyStatus = getGitStatusFn(projectRoot);
    if (dirtyStatus && dirtyStatus.trim()) {
      throw new Error('Working tree hiện đang bẩn. Hãy commit hoặc stash thay đổi trước khi chạy `taxsentry update` để tránh conflict.');
    }

    const branch = getCurrentBranchFn(projectRoot) || 'main';
    info(`Đang fast-forward source từ ${repositoryUrl} [branch: ${branch}]...`);
    runGitFn(['fetch', 'origin', branch], projectRoot);
    runGitFn(['pull', '--ff-only', 'origin', branch], projectRoot);
  } else {
    const branch = deps.branch ?? 'main';
    info(`Không phát hiện checkout Git tại package hiện hành. Đang dùng staging clone từ ${repositoryUrl}...`);
    const stageRoot = prepareStageFn(repositoryUrl, branch);
    try {
      replaceManagedPathsFn(stageRoot, projectRoot);
    } finally {
      rmSync(stageRoot, { recursive: true, force: true });
    }
  }

  info('Đang kiểm tra Python để refresh runtime sau update...');
  const pyResult = detectPythonFn();
  printDetectionResultFn(pyResult);
  if (!pyResult.found) {
    const instructions = getInstallInstructionsFn().join('\n');
    throw new Error(`Không thể hoàn tất update vì thiếu Python 3.10+.\n${instructions}`);
  }

  await refreshInstalledRuntimeFn(pyResult.command);

  success('TaxSentry đã cập nhật source và đồng bộ runtime thành công.');
  console.log(chalk.dim('Gợi ý: chạy `taxsentry doctor` hoặc `npm run test` nếu Sếp muốn verify sâu thêm.'));

  return {
    projectRoot,
    repositoryUrl,
    pythonCommand: pyResult.command,
  };
}

export default async function updateCommand(deps = {}) {
  try {
    await runUpdate(deps);
  } catch (err) {
    error(`Update thất bại: ${err.message}`);
    throw err;
  }
}
