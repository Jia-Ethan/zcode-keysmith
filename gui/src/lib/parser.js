// lib/parser.js — zcode-keysmith JSON 契约（zcode-keysmith/v1）→ 视图模型

export const SCHEMA = "zcode-keysmith/v1";

export class ContractError extends Error {
  constructor(message, output = {}) {
    super(message);
    this.name = "ContractError";
    this.output = output;
    this.exitCode = output.exit_code ?? null;
    this.timedOut = Boolean(output.timed_out);
  }
}

export function extractJson(stdout) {
  const text = String(stdout ?? "");
  const start = text.indexOf("{");
  if (start === -1) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') inString = true;
    else if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) {
        try {
          return JSON.parse(text.slice(start, i + 1));
        } catch {
          return null;
        }
      }
    }
  }
  return null;
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asBool(value) {
  return value === true;
}

export function parseContract(output) {
  if (output?.timed_out) {
    throw new ContractError("CLI 执行超时", output);
  }
  const doc = extractJson(output?.stdout);
  if (!doc || typeof doc !== "object") {
    throw new ContractError("CLI 未输出稳定 JSON", output);
  }
  if (doc.schema !== undefined && doc.schema !== SCHEMA) {
    throw new ContractError(`不支持的契约版本: ${String(doc.schema)}`, output);
  }
  doc.exitCode = output?.exit_code ?? null;
  doc.stderr = String(output?.stderr ?? "");
  return doc;
}

export function mapAction(action) {
  return {
    action: typeof action?.action === "string" ? action.action : "unknown",
    path: typeof action?.path === "string" ? action.path : "",
    detail: typeof action?.detail === "string" ? action.detail : "",
  };
}

export function gateReport(report) {
  const reasons = [];
  if (report.exitCode !== 0) reasons.push(`exit ${report.exitCode ?? "unknown"}`);
  if (report.blockers.length > 0) reasons.push(...report.blockers);
  if (!report.ok && report.blockers.length === 0) {
    reasons.push(report.error || "ok=false");
  }
  return { ok: reasons.length === 0, reasons };
}

export function parseWriteReport(output) {
  const doc = parseContract(output);
  const blockers = asArray(doc.blockers).map(String);
  const report = {
    schema: doc.schema ?? null,
    operation: typeof doc.operation === "string" ? doc.operation : "unknown",
    mode: doc.mode === "execute" ? "execute" : "preview",
    ok: asBool(doc.ok),
    actions: asArray(doc.actions).map(mapAction),
    warnings: asArray(doc.warnings).map(String),
    blockers,
    backups: asArray(doc.backups),
    error: typeof doc.error === "string" ? doc.error : null,
    managedDir: typeof doc.managed_dir === "string" ? doc.managed_dir : null,
    write: asBool(doc.write),
    removed: asArray(doc.removed),
    reloadRequired: false,
    exitCode: doc.exitCode,
    stderr: doc.stderr,
    raw: doc,
  };
  report.gate = gateReport(report);
  return report;
}

export function parseDoctorReport(output) {
  const doc = parseContract(output);
  const managed = doc.managed && typeof doc.managed === "object" ? doc.managed : {};
  const runtime = doc.runtime && typeof doc.runtime === "object" ? doc.runtime : {};
  const model = {
    schema: doc.schema ?? null,
    operation: "doctor",
    ok: asBool(doc.ok),
    managed: {
      dir: typeof managed.dir === "string" ? managed.dir : null,
      systemFile: managed.system_file || null,
      systemFileExists: asBool(managed.system_file_exists),
      wrapper: managed.wrapper || null,
      wrapperExists: asBool(managed.wrapper_exists),
      envScript: managed.env_script || null,
      envScriptExists: asBool(managed.env_script_exists),
      configFile: managed.config_file || null,
      configFileExists: asBool(managed.config_file_exists),
      launchAgent: managed.launch_agent || null,
      launchAgentExists: asBool(managed.launch_agent_exists),
    },
    runtime: {
      path: runtime.path || null,
      exists: asBool(runtime.exists),
      patchable: asBool(runtime.patchable),
      nodeCommand: runtime.node_command || null,
      nodeCommandExists: asBool(runtime.node_command_exists),
    },
    env: doc.env && typeof doc.env === "object" ? doc.env : {},
    backups: asArray(doc.backups),
    blockers: asArray(doc.blockers).map(String),
    warnings: asArray(doc.warnings).map(String),
    error: typeof doc.error === "string" ? doc.error : null,
    exitCode: doc.exitCode,
    stderr: doc.stderr,
    raw: doc,
  };
  if (model.managed.wrapperExists && model.managed.systemFileExists) model.health = "healthy";
  else if (model.managed.wrapperExists || model.managed.systemFileExists) model.health = "partial-install";
  else model.health = "not-installed";
  return model;
}

export function buildManagedArgs({ managedDir, launchAgent, zcodeRuntime, nodeCommand, systemFile } = {}) {
  const args = [];
  if (managedDir) args.push("--managed-dir", managedDir);
  if (launchAgent) args.push("--launch-agent", launchAgent);
  if (zcodeRuntime) args.push("--zcode-runtime", zcodeRuntime);
  if (nodeCommand) args.push("--node-command", nodeCommand);
  if (systemFile) args.push("--system-file", systemFile);
  return args;
}

export function buildInstallArgs(options = {}) {
  return ["install", ...buildManagedArgs(options)];
}

export function buildDoctorArgs(options = {}) {
  return ["doctor", ...buildManagedArgs(options)];
}

export function buildUninstallArgs(options = {}) {
  return ["uninstall", ...buildManagedArgs(options)];
}
