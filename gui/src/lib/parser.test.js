import { describe, expect, it } from "vitest";
import { SCHEMA, parseDoctorReport, parseWriteReport, buildInstallArgs, buildDoctorArgs } from "./parser.js";

describe("parseDoctorReport", () => {
  it("maps managed / runtime / env and health", () => {
    const model = parseDoctorReport({
      stdout: JSON.stringify({
        schema: SCHEMA,
        operation: "doctor",
        mode: "preview",
        ok: true,
        managed: { dir: "/tmp/m", wrapper_exists: true, system_file_exists: true, wrapper: "/tmp/m/bin/w" },
        runtime: { path: "/tmp/zcode.cjs", exists: true, patchable: true },
        env: { ZCODE_KEYSMITH_SYSTEM_FILE: { session: "not_set", persistent: "not_set" } },
        backups: [{ path: "/tmp/m/x.bak_1", name: "x.bak_1" }],
        actions: [],
        warnings: [],
        blockers: [],
        exit_status: 0,
      }),
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });
    expect(model.health).toBe("healthy");
    expect(model.managed.wrapperExists).toBe(true);
    expect(model.runtime.patchable).toBe(true);
    expect(model.backups).toHaveLength(1);
  });
});

describe("parseWriteReport / args", () => {
  it("parses install preview and builds subcommand args without --lang", () => {
    const report = parseWriteReport({
      stdout: JSON.stringify({
        schema: SCHEMA,
        operation: "install",
        mode: "preview",
        ok: true,
        write: false,
        actions: [{ action: "plan", path: "/tmp/system-role.md", detail: "system_file" }],
        warnings: [],
        blockers: [],
        exit_status: 0,
      }),
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });
    expect(report.gate.ok).toBe(true);
    expect(buildInstallArgs({ managedDir: "/tmp/m", systemFile: "/tmp/s.md" })).toEqual([
      "install", "--managed-dir", "/tmp/m", "--system-file", "/tmp/s.md",
    ]);
    expect(buildDoctorArgs({ managedDir: "/tmp/m" })).toEqual(["doctor", "--managed-dir", "/tmp/m"]);
  });
});
