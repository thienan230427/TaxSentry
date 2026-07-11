import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export type RuntimePaths = {
  home: string;
  runtime: string;
  venv: string;
  python: string;
  versionFile: string;
};

type CommandRunner = (command: string, args: string[]) => { status: number | null; error?: Error };

export function paths(home = process.env.TAXSENTRY_HOME || join(homedir(), ".taxsentry"), platform = process.platform): RuntimePaths {
  const runtime = join(home, "runtime");
  const venv = join(runtime, "venv");
  return {
    home,
    runtime,
    venv,
    python: join(venv, platform === "win32" ? "Scripts/python.exe" : "bin/python"),
    versionFile: join(runtime, "installed-version"),
  };
}

export function findUv(env: NodeJS.ProcessEnv = process.env, platform = process.platform): string | undefined {
  if (env.TAXSENTRY_UV && existsSync(env.TAXSENTRY_UV)) return env.TAXSENTRY_UV;
  const executable = platform === "win32" ? "uv.exe" : "uv";
  return (env.PATH || "").split(delimiter).filter(Boolean).map((part) => join(part, executable)).find(existsSync);
}

export function packageRoot(): string {
  return dirname(dirname(dirname(fileURLToPath(import.meta.url))));
}

export function bundledWheel(root = packageRoot()): string {
  const vendor = existsSync(join(root, "dist", "vendor")) ? join(root, "dist", "vendor") : join(root, "vendor");
  const wheels = readdirSync(vendor).filter((name) => name.endsWith(".whl"));
  if (wheels.length !== 1) throw new Error(`Expected one bundled wheel, found ${wheels.length}`);
  return join(vendor, wheels[0]);
}

export function ensureRuntime(
  version: string,
  options: { home?: string; root?: string; platform?: NodeJS.Platform; uv?: string; run?: CommandRunner } = {},
): RuntimePaths {
  const runtime = paths(options.home, options.platform);
  const installed = existsSync(runtime.versionFile) ? readFileSync(runtime.versionFile, "utf8").trim() : "";
  if (installed === version && existsSync(runtime.python)) return runtime;

  const uv = options.uv || findUv(process.env, options.platform);
  if (!uv) throw new Error("Không tìm thấy uv. Cài tại https://docs.astral.sh/uv/ rồi chạy lại.");
  const run = options.run || ((command, args) => spawnSync(command, args, { stdio: "inherit", shell: false }));
  mkdirSync(runtime.runtime, { recursive: true });
  if (!existsSync(runtime.python)) checked(run(uv, ["venv", runtime.venv, "--python", ">=3.11,<3.14"]), "Không thể tạo Python runtime");
  checked(run(uv, ["pip", "install", "--python", runtime.python, "--force-reinstall", bundledWheel(options.root)]), "Không thể cài TaxSentry Python core");
  writeFileSync(runtime.versionFile, `${version}\n`, "utf8");
  return runtime;
}

function checked(result: { status: number | null; error?: Error }, message: string): void {
  if (result.error || result.status !== 0) throw new Error(`${message}${result.error ? `: ${result.error.message}` : ""}`);
}

export function forwardToPython(
  python: string,
  args: string[],
  spawnProcess: typeof spawn = spawn,
): Promise<number> {
  return new Promise((resolve, reject) => {
    const child = spawnProcess(python, ["-m", "taxsentry", ...args], { stdio: "inherit", shell: false });
    const forward = (signal: NodeJS.Signals) => {
      try {
        child.kill(signal);
      } catch {
        // The child may already have received Ctrl+C through the inherited terminal.
      }
    };
    const onSigint = () => forward("SIGINT");
    const onSigterm = () => forward("SIGTERM");
    process.once("SIGINT", onSigint);
    process.once("SIGTERM", onSigterm);
    const cleanup = () => {
      process.off("SIGINT", onSigint);
      process.off("SIGTERM", onSigterm);
    };
    child.once("error", (error) => {
      cleanup();
      reject(error);
    });
    child.once("close", (code, signal) => {
      cleanup();
      resolve(code ?? (signal ? 128 : 1));
    });
  });
}
