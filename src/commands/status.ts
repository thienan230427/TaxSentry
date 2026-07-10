import { startForeground } from '../launcher.ts';

export default async function statusCommand() {
  const exitCode = startForeground(['status']);
  if (exitCode !== 0) process.exitCode = exitCode;
}

