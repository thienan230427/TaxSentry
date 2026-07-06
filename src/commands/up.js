import { isConfigured } from '../utils/paths.js';
import { runSetup } from './setup.js';
import { startBackground } from '../launcher.js';

export default async function upCommand() {
  if (!isConfigured()) {
    await runSetup({ resetExisting: true });
  }
  const child = startBackground(['tui']);
  if (!child) {
    process.exitCode = 1;
  }
}
