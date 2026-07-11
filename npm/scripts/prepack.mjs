import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync } from "node:fs";
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
for (const name of readdirSync(vendor)) if (name.endsWith(".whl")) rmSync(join(vendor, name));
execFileSync("uv", ["build", "--wheel", repository, "--out-dir", vendor], { stdio: "inherit" });
rmSync(join(vendor, ".gitignore"), { force: true });
if (readdirSync(vendor).filter((name) => name.endsWith(".whl")).length !== 1) throw new Error("uv build did not produce exactly one wheel");
if (!existsSync(join(repository, "LICENSE"))) throw new Error("LICENSE is missing");
