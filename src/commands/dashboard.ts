import { startForeground } from '../launcher.ts';

export default async function dashboardCommand() {
  const exitCode = startForeground(['dashboard']);
  if (exitCode !== 0) process.exitCode = exitCode;
}

