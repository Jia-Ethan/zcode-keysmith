import { describe, expect, it } from "vitest";
import { normalizeBackup } from "./ReportView.jsx";

describe("normalizeBackup", () => {
  it("keeps CLI install backup strings visible", () => {
    expect(normalizeBackup("/tmp/config.json.bak_20260829")).toEqual({
      path: "/tmp/config.json.bak_20260829",
      sizeBytes: null,
      sha256: "",
      created: "",
    });
  });

  it("accepts structured doctor and legacy report records", () => {
    expect(normalizeBackup({ path: "/tmp/a.bak", name: "a.bak" }).path).toBe("/tmp/a.bak");
    expect(normalizeBackup({ backupPath: "/tmp/b.bak", sizeBytes: 42 }).path).toBe("/tmp/b.bak");
    expect(normalizeBackup({ target: "/tmp/c", sha256: "abc" })).toMatchObject({
      path: "/tmp/c",
      sha256: "abc",
    });
  });
});
