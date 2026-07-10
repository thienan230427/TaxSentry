import { isConfigured } from '../utils/paths.ts';
import { runSetup } from './setup.ts';
import { startBackground } from '../launcher.ts';

export default async function upCommand() {
  if (!isConfigured()) {
    await runSetup({ resetExisting: true });
  }
  const child = startBackground(['tui']);
  if (!child) {
    process.exitCode = 1;
  }
}

