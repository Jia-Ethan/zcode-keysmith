// PyInstaller onefile sidecar 构建（仅本机原生目标）。
// zcode-keysmith.py 通过 examples/system-role.md 定位源指令；frozen 时 REPO_ROOT
// 必须指向 sys._MEIPASS。打包前写入等效 source patch。
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const guiDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoDir = resolve(guiDir, "..");
const sourcePath = join(repoDir, "zcode-keysmith.py");
const examplesDir = join(repoDir, "examples");
const expectedCliVersion = readFileSync(join(repoDir, "VERSION"), "utf8").trim();

const TARGETS = {
  "aarch64-apple-darwin": { platform: "darwin", arch: "arm64", extension: "", dataSeparator: ":" },
  "x86_64-pc-windows-msvc": { platform: "win32", arch: "x64", extension: ".exe", dataSeparator: ";" },
};

function argument(name) {
  const index = process.argv.indexOf(name);
  return index === -1 ? null : process.argv[index + 1];
}

function hostTarget() {
  if (process.platform === "darwin" && process.arch === "arm64") return "aarch64-apple-darwin";
  if (process.platform === "win32" && process.arch === "x64") return "x86_64-pc-windows-msvc";
  throw new Error(`Unsupported native build host: ${process.platform}/${process.arch}`);
}

const target = argument("--target") || process.env.TAURI_ENV_TARGET_TRIPLE || hostTarget();
const targetConfig = TARGETS[target];
if (!targetConfig) throw new Error(`Unsupported target: ${target}`);
if (process.platform !== targetConfig.platform || process.arch !== targetConfig.arch) {
  throw new Error(`PyInstaller sidecars must be built natively: ${target} requires ${targetConfig.platform}/${targetConfig.arch}`);
}
if (!existsSync(sourcePath)) throw new Error(`CLI source not found: ${sourcePath}`);
if (!existsSync(examplesDir)) throw new Error(`examples/ directory not found: ${examplesDir}`);

const originalRepoRoot = "REPO_ROOT = Path(__file__).resolve().parent";
const frozenRepoRoot = 'REPO_ROOT = Path(sys._MEIPASS) if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parent';
const source = readFileSync(sourcePath, "utf8");
let sidecarSource;
if (source.includes('getattr(sys, "frozen", False)') && source.includes("_MEIPASS")) {
  sidecarSource = source;
} else if (source.includes(originalRepoRoot)) {
  sidecarSource = source.replace(originalRepoRoot, frozenRepoRoot);
} else {
  throw new Error("CLI REPO_ROOT contract changed; update the frozen-source compatibility check before packaging");
}

const buildRoot = join(guiDir, "src-tauri", "target", "sidecar-build", target);
const patchedSource = join(buildRoot, "zcode-keysmith-frozen.py");
const distDir = join(buildRoot, "dist");
const workDir = join(buildRoot, "work");
const specDir = join(buildRoot, "spec");
mkdirSync(buildRoot, { recursive: true });
rmSync(distDir, { recursive: true, force: true });
rmSync(workDir, { recursive: true, force: true });
rmSync(specDir, { recursive: true, force: true });
writeFileSync(patchedSource, sidecarSource, "utf8");

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const pythonEnv = { ...process.env, PYTHONNOUSERSITE: "1" };
delete pythonEnv.PYTHONHOME;
delete pythonEnv.PYTHONPATH;
delete pythonEnv.PYTHONUSERBASE;

const result = spawnSync(
  python,
  [
    "-m",
    "PyInstaller",
    "--clean",
    "--noconfirm",
    "--onefile",
    "--name",
    "zcode-keysmith-cli",
    "--distpath",
    distDir,
    "--workpath",
    workDir,
    "--specpath",
    specDir,
    "--add-data",
    `${examplesDir}${targetConfig.dataSeparator}examples`,
    patchedSource,
  ],
  { cwd: guiDir, encoding: "utf8", stdio: "inherit", env: pythonEnv },
);
if (result.error) throw result.error;
if (result.status !== 0) {
  throw new Error(`PyInstaller failed with exit code ${result.status}. Install gui/requirements-build.txt in the active Python environment.`);
}

const builtPath = join(distDir, `zcode-keysmith-cli${targetConfig.extension}`);
if (!existsSync(builtPath)) throw new Error(`PyInstaller output missing: ${builtPath}`);

const binariesDir = join(guiDir, "src-tauri", "binaries");
const destination = join(binariesDir, `zcode-keysmith-cli-${target}${targetConfig.extension}`);
const temporary = `${destination}.tmp-${process.pid}`;
mkdirSync(binariesDir, { recursive: true });
copyFileSync(builtPath, temporary);
if (process.platform !== "win32") chmodSync(temporary, 0o755);
renameSync(temporary, destination);

const smoke = spawnSync(destination, ["--version"], { encoding: "utf8" });
if (smoke.error) throw smoke.error;
const reportedVersion = smoke.stdout.trim().split(/\s+/).at(-1);
if (smoke.status !== 0 || reportedVersion !== expectedCliVersion) {
  throw new Error(`Frozen sidecar version smoke failed: ${smoke.stderr || smoke.stdout}`);
}

const smokeHome = mkdtempSync(join(tmpdir(), "zcode-keysmith-smoke-"));
const doctorSmoke = spawnSync(
  destination,
  [
    "doctor",
    "--json",
    "--managed-dir",
    smokeHome,
    "--launch-agent",
    join(smokeHome, "com.jia.zcode-keysmith.env.plist"),
    "--zcode-runtime",
    join(smokeHome, "zcode.cjs"),
    "--node-command",
    join(smokeHome, "node"),
  ],
  { encoding: "utf8" },
);
if (doctorSmoke.error) throw doctorSmoke.error;
if (doctorSmoke.status !== 0 || !doctorSmoke.stdout.includes('"schema": "zcode-keysmith/v1"')) {
  throw new Error(`Frozen sidecar doctor --json smoke failed: ${doctorSmoke.stderr || doctorSmoke.stdout}`);
}
if (doctorSmoke.stdout.includes("/Library/LaunchAgents/com.jia.zcode-keysmith.env.plist")) {
  throw new Error("Frozen sidecar doctor smoke probed the live LaunchAgent; refusing to package");
}
rmSync(smokeHome, { recursive: true, force: true });

console.log(`Built ${destination}`);
