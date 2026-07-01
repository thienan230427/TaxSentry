import { startForeground } from '../launcher.js';

export default async function dashboardCommand() {
  const exitCode = startForeground(['dashboard']);
  if (exitCode !== 0) process.exitCode = exitCode;
}
