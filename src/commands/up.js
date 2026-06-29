import { isConfigured } from '../utils/paths.js';
import { runSetup } from './setup.js';
import { startBackground } from '../launcher.js';

export default async function upCommand() {
  if (!isConfigured()) {
    await runSetup({ resetExisting: true });
  }
  startBackground(['tui']);
}
