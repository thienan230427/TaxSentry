import { startForeground } from '../launcher.js';

export default async function doctorCommand() {
  const exitCode = startForeground(['doctor']);
  if (exitCode !== 0) process.exitCode = exitCode;
}
