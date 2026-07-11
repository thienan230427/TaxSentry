#!/usr/bin/env node

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { ensureRuntime, forwardToPython, packageRoot } from "./runtime.js";

const metadata = JSON.parse(readFileSync(join(packageRoot(), "package.json"), "utf8")) as { version: string };
const args = process.argv.slice(2);

if (args.length === 1 && (args[0] === "--version" || args[0] === "-V")) {
  console.log(metadata.version);
  process.exit(0);
}

if (args.length === 1 && (args[0] === "--help" || args[0] === "-h")) {
  console.log(`TaxSentry ${metadata.version}\n\nUsage: taxsentry [command] [options]\n\nCommands: setup, doctor, status, worker, gateway, jobs, report, service, auth`);
  process.exit(0);
}

try {
  const runtime = ensureRuntime(metadata.version);
  process.exitCode = await forwardToPython(runtime.python, args);
} catch (error) {
  console.error(`TaxSentry: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}
