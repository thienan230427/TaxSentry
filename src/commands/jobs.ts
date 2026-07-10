import { startForeground } from '../launcher.ts';

export default async function jobsCommand() {
  const exitCode = startForeground(['jobs']);
  if (exitCode !== 0) process.exitCode = exitCode;
}

