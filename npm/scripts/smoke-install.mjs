import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const temp = mkdtempSync(join(tmpdir(), "taxsentry-smoke-"));
const npmCli = process.env.npm_execpath;
if (!npmCli) throw new Error("npm_execpath is missing");

let tarball;
try {
  const env = {
    ...process.env,
    npm_config_cache: join(temp, "npm-cache"),
    TAXSENTRY_HOME: join(temp, "home"),
    PYTHON_KEYRING_BACKEND: "keyring.backends.null.Keyring",
  };
  const packOutput = execFileSync(process.execPath, [npmCli, "pack", "--json"], { cwd: root, env, encoding: "utf8" });
  const jsonStart = packOutput.lastIndexOf("\n[");
  const packed = JSON.parse(packOutput.slice(jsonStart < 0 ? 0 : jsonStart + 1));
  tarball = join(root, packed[0].filename);
  const files = packed[0].files.map((item) => item.path);
  if (!files.some((path) => path.startsWith("dist/vendor/") && path.endsWith(".whl"))) throw new Error("bundled wheel is missing");
  if (files.some((path) => path.startsWith("ui/") || path.includes("web/static"))) throw new Error("web assets leaked into the tarball");

  execFileSync(process.execPath, [npmCli, "install", "--prefix", temp, tarball], { env, stdio: "inherit" });
  const packageRoot = join(temp, "node_modules", "taxsentry");
  const cli = join(packageRoot, "dist", "src", "cli.js");
  const version = JSON.parse(readFileSync(join(root, "package.json"), "utf8")).version;
  const { ensureRuntime } = await import(pathToFileURL(join(packageRoot, "dist", "src", "runtime.js")).href);
  const runtime = ensureRuntime(version, { home: env.TAXSENTRY_HOME, root: packageRoot });
  for (const args of [["--version"], ["--help"]]) execFileSync(process.execPath, [cli, ...args], { env, stdio: "inherit" });

  if (!readFileSync(join(temp, "home", "runtime", "installed-version"), "utf8").includes(version)) throw new Error("runtime version sentinel was not created");
  const verify = "import importlib.util; assert importlib.util.find_spec('taxsentry.control_server') is None; assert importlib.util.find_spec('taxsentry.service_control') is None; from taxsentry.cockpit import banner_text; print(banner_text({'provider': {'kind': 'smoke', 'model': 'test'}, 'gmail': {'enabled': False}, 'telegram': {'enabled': False}}, 80))";
  execFileSync(runtime.python, ["-c", verify], { env, stdio: "inherit" });
} finally {
  if (tarball) rmSync(tarball, { force: true });
  rmSync(temp, { recursive: true, force: true });
}
