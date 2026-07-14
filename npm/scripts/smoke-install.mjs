import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const temp = mkdtempSync(join(tmpdir(), "taxsentry-smoke-"));
const npmCli = process.env.npm_execpath;
if (!npmCli) throw new Error("npm_execpath is missing");

let tarball;
try {
  const env = { ...process.env, npm_config_cache: join(temp, "npm-cache") };
  const packed = JSON.parse(execFileSync(process.execPath, [npmCli, "pack", "--json"], { cwd: root, env, encoding: "utf8" }));
  tarball = join(root, packed[0].filename);
  execFileSync(process.execPath, [npmCli, "install", "--prefix", temp, tarball], { env, stdio: "inherit" });
  const cli = join(temp, "node_modules", "taxsentry", "dist", "src", "cli.js");
  env.TAXSENTRY_HOME = join(temp, "home");
  for (const args of [["--version"], ["--help"], ["status"]])
    execFileSync(process.execPath, [cli, ...args], { env, stdio: "inherit" });
  const version = JSON.parse(readFileSync(join(root, "package.json"), "utf8").toString()).version;
  if (!readFileSync(join(temp, "home", "runtime", "installed-version"), "utf8").includes(version))
    throw new Error("runtime version sentinel was not created");
} finally {
  if (tarball) rmSync(tarball, { force: true });
  rmSync(temp, { recursive: true, force: true });
}
