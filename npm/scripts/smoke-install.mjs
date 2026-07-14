import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const temp = mkdtempSync(join(tmpdir(), "taxsentry-smoke-"));
const npmCli = process.env.npm_execpath;
if (!npmCli) throw new Error("npm_execpath is missing");

function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

async function waitForDashboard(port) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/bootstrap`);
      if (response.ok && (await response.json()).authenticated === false) return;
    } catch {
      // The clean runtime is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("dashboard health check timed out");
}

let tarball;
try {
  const env = { ...process.env, npm_config_cache: join(temp, "npm-cache") };
  const packOutput = execFileSync(process.execPath, [npmCli, "pack", "--json"], { cwd: root, env, encoding: "utf8" });
  const jsonStart = packOutput.lastIndexOf("\n[");
  const packed = JSON.parse(packOutput.slice(jsonStart < 0 ? 0 : jsonStart + 1));
  tarball = join(root, packed[0].filename);
  execFileSync(process.execPath, [npmCli, "install", "--prefix", temp, tarball], { env, stdio: "inherit" });
  const cli = join(temp, "node_modules", "taxsentry", "dist", "src", "cli.js");
  env.TAXSENTRY_HOME = join(temp, "home");
  for (const args of [["--version"], ["--help"], ["status"]])
    execFileSync(process.execPath, [cli, ...args], { env, stdio: "inherit" });
  const version = JSON.parse(readFileSync(join(root, "package.json"), "utf8").toString()).version;
  if (!readFileSync(join(temp, "home", "runtime", "installed-version"), "utf8").includes(version))
    throw new Error("runtime version sentinel was not created");

  const python = join(temp, "home", "runtime", "venv", process.platform === "win32" ? "Scripts" : "bin", process.platform === "win32" ? "python.exe" : "python");
  const port = await freePort();
  env.PYTHON_KEYRING_BACKEND = "keyring.backends.null.Keyring";
  const dashboard = spawn(python, ["-m", "taxsentry", "start", "--no-open", "--port", String(port)], {
    env,
    stdio: "ignore",
  });
  try {
    await waitForDashboard(port);
  } finally {
    dashboard.kill();
  }
} finally {
  if (tarball) rmSync(tarball, { force: true });
  rmSync(temp, { recursive: true, force: true });
}
