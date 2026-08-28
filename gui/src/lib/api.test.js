import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const invokeMock = vi.fn();
vi.mock("@tauri-apps/api/core", () => ({ invoke: (...args) => invokeMock(...args) }));

function createStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  };
}

let api;
let store;
let settings;

beforeEach(async () => {
  vi.resetModules();
  invokeMock.mockReset();
  vi.stubGlobal("localStorage", createStorage());
  settings = await import("./settings.js");
  store = await import("./store.js");
  store.resetOperationCoordinatorForTests();
  api = await import("./api.js");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchStatus", () => {
  it("calls doctor --json without --lang", async () => {
    settings.saveSettings({ defaultManagedDir: "/tmp/m", lang: "zh-CN" });
    invokeMock.mockResolvedValue({
      stdout: JSON.stringify({
        schema: "zcode-keysmith/v1",
        operation: "doctor",
        ok: true,
        managed: { dir: "/tmp/m", wrapper_exists: false, system_file_exists: false },
        runtime: {},
        env: {},
        backups: [],
        actions: [],
        warnings: [],
        blockers: [],
        exit_status: 0,
      }),
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });
    const model = await api.fetchStatus();
    expect(model.health).toBe("not-installed");
    const args = invokeMock.mock.calls[0][1].args;
    expect(args[0]).toBe("doctor");
    expect(args).toContain("--json");
    expect(args).not.toContain("--lang");
    expect(args).toEqual(["doctor", "--managed-dir", "/tmp/m", "--json"]);
  });
});

describe("preview/execute install", () => {
  it("preview uses --dry-run; execute uses --yes", async () => {
    const payload = {
      schema: "zcode-keysmith/v1",
      operation: "install",
      mode: "preview",
      ok: true,
      actions: [],
      warnings: [],
      blockers: [],
      exit_status: 0,
    };
    invokeMock.mockResolvedValue({ stdout: JSON.stringify(payload), stderr: "", exit_code: 0, timed_out: false });
    await api.previewDeploy({ managedDir: "/tmp/m" });
    expect(invokeMock.mock.calls[0][1].args).toEqual(["install", "--managed-dir", "/tmp/m", "--dry-run", "--json"]);
    invokeMock.mockClear();
    invokeMock.mockResolvedValue({
      stdout: JSON.stringify({ ...payload, mode: "execute" }),
      stderr: "",
      exit_code: 0,
      timed_out: false,
    });
    await api.executeDeploy({ managedDir: "/tmp/m" });
    expect(invokeMock.mock.calls[0][1].args).toEqual(["install", "--managed-dir", "/tmp/m", "--yes", "--json"]);
  });
});
