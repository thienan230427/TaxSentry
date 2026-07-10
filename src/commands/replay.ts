import { startForeground } from '../launcher.ts';

export default async function replayCommand(sessionId = '') {
  const args = sessionId ? ['replay', sessionId] : ['replay'];
  const exitCode = startForeground(args);
  if (exitCode !== 0) process.exitCode = exitCode;
}

