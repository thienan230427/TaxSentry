import { startForeground } from '../launcher.js';

export default async function statusCommand() {
  const exitCode = startForeground(['status']);
  if (exitCode !== 0) process.exitCode = exitCode;
}
