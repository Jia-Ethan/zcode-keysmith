import { beforeEach, describe, expect, it, vi } from "vitest";

const KEY = "zcode-keysmith-gui:settings";

function createStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: vi.fn((key) => values.get(key) ?? null),
    setItem: vi.fn((key, value) => values.set(key, value)),
    value: (key) => values.get(key),
  };
}

beforeEach(() => {
  vi.resetModules();
});

describe("CLI 路径设置", () => {
  it("读取旧设置时规范化并持久化手动路径", async () => {
    const storage = createStorage({
      [KEY]: JSON.stringify({ cliPath: "  /tmp/zcode-keysmith.py  " }),
    });
    vi.stubGlobal("localStorage", storage);
    const { getSettings } = await import("./settings.js");

    expect(getSettings().cliPath).toBe("/tmp/zcode-keysmith.py");
    expect(JSON.parse(storage.value(KEY)).cliPath).toBe("/tmp/zcode-keysmith.py");
  });

  it("保存时持久化规范化路径供后续 CLI 调用读取", async () => {
    const storage = createStorage();
    vi.stubGlobal("localStorage", storage);
    const { getSettings, saveSettings } = await import("./settings.js");

    saveSettings({ cliPath: "  /tmp/zcode-keysmith.py  " });

    expect(getSettings().cliPath).toBe("/tmp/zcode-keysmith.py");
    expect(JSON.parse(storage.value(KEY)).cliPath).toBe("/tmp/zcode-keysmith.py");
  });

  it("忽略合法 JSON 中的非对象设置值", async () => {
    const storage = createStorage({ [KEY]: "null" });
    vi.stubGlobal("localStorage", storage);
    const { getSettings } = await import("./settings.js");

    expect(getSettings()).toMatchObject({
      cliPath: "",
      defaultManagedDir: "",
      lang: "zh-CN",
      theme: "system",
    });
  });
});
