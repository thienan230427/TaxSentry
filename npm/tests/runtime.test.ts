import { EventEmitter } from "node:events";
import { chmodSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { mkdtempSync } from "node:fs";
import test from "node:test";
import assert from "node:assert/strict";

import { ensureRuntime, findUv, forwardToPython, paths } from "../src/runtime.js";

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "taxsentry-npm-"));
  const vendor = join(root, "vendor");
  mkdirSync(vendor);
  writeFileSync(join(vendor, "taxsentry_agent-2.0.0-py3-none-any.whl"), "wheel");
  return { root, home: join(root, "home") };
}

test("findUv uses the explicit executable and returns undefined when absent", () => {
  const root = mkdtempSync(join(tmpdir(), "taxsentry-uv-"));
  const uv = join(root, process.platform === "win32" ? "uv.exe" : "uv");
  writeFileSync(uv, "");
  chmodSync(uv, 0o755);
  assert.equal(findUv({ TAXSENTRY_UV: uv }), uv);
  assert.equal(findUv({ PATH: "" }), undefined);
});

test("ensureRuntime installs once and reinstalls only on version drift", () => {
  const { root, home } = fixture();
  const runtime = paths(home);
  const calls: string[][] = [];
  const run = (_command: string, args: string[]) => {
    calls.push(args);
    if (args[0] === "venv") {
      mkdirSync(join(runtime.venv, process.platform === "win32" ? "Scripts" : "bin"), { recursive: true });
      writeFileSync(runtime.python, "");
    }
    return { status: 0 };
  };

  ensureRuntime("2.0.0", { home, root, uv: "uv", run });
  ensureRuntime("2.0.0", { home, root, uv: "uv", run });
  ensureRuntime("2.0.1", { home, root, uv: "uv", run });

  assert.equal(calls.filter((args) => args[0] === "venv").length, 1);
  assert.equal(calls.filter((args) => args[0] === "pip").length, 2);
});

test("forwardToPython preserves unicode arguments and exit code", async () => {
  let invocation: string[] = [];
  const spawn = ((command: string, args: string[]) => {
    invocation = [command, ...args];
    const child = new EventEmitter() as EventEmitter & { kill: () => boolean };
    child.kill = () => true;
    queueMicrotask(() => child.emit("close", 7, null));
    return child;
  }) as never;

  assert.equal(await forwardToPython("python", ["report", "báo cáo tháng 5"], spawn), 7);
  assert.deepEqual(invocation, ["python", "-m", "taxsentry", "report", "báo cáo tháng 5"]);
});
