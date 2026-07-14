import { execFileSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const repository = dirname(root);
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const pythonVersion = readFileSync(join(repository, "pyproject.toml"), "utf8").match(/^version = "([^"]+)"/m)?.[1];
const moduleVersion = readFileSync(join(repository, "src", "taxsentry", "__init__.py"), "utf8").match(/^__version__ = "([^"]+)"/m)?.[1];
if (pkg.version !== pythonVersion || pkg.version !== moduleVersion) throw new Error(`Version mismatch: npm=${pkg.version}, pyproject=${pythonVersion}, module=${moduleVersion}`);

const vendor = join(root, "dist", "vendor");
mkdirSync(vendor, { recursive: true });
const build = mkdtempSync(join(tmpdir(), "taxsentry-wheel-"));
try {
  execFileSync("uv", ["build", "--wheel", repository, "--out-dir", build], {
    stdio: "inherit",
    env: { ...process.env, UV_CACHE_DIR: join(tmpdir(), "taxsentry-uv-cache") },
  });
  const wheels = readdirSync(build).filter((name) => name.endsWith(".whl"));
  if (wheels.length !== 1) throw new Error("uv build did not produce exactly one wheel");
  copyFileSync(join(build, wheels[0]), join(vendor, wheels[0]));
  for (const name of readdirSync(vendor)) if (name.endsWith(".whl") && name !== wheels[0]) rmSync(join(vendor, name));
} finally {
  rmSync(build, { recursive: true, force: true });
}
if (!existsSync(join(repository, "LICENSE"))) throw new Error("LICENSE is missing");
