import { startForeground } from '../launcher.ts';

export default async function doctorCommand() {
  const exitCode = startForeground(['doctor']);
  if (exitCode !== 0) process.exitCode = exitCode;
}

