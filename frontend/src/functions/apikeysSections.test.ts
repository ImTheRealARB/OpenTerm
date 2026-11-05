import { describe, expect, it } from "vitest";
import { SECTIONS, groupRows, isHeaderRow, sectionOf } from "./apikeysSections";

// vitest has no @types/node here: read the backend file through Node directly (same trick as themes.test.ts).
const nodeFs = (globalThis as unknown as { process: { getBuiltinModule(id: string): { readFileSync(p: URL, enc: string): string } } }).process.getBuiltinModule("node:fs");
const keysPy = nodeFs.readFileSync(new URL("../../../backend/openterm/keys.py", import.meta.url), "utf8");
const BACKEND_NAMES = [...keysPy.matchAll(/KeySpec\(\s*"([a-z_]+)"/g)].map((m) => m[1]);

describe("APIKEYS sections", () => {
  it("finds the backend providers", () => {
    expect(BACKEND_NAMES.length).toBeGreaterThan(25);
  });
  it("every backend provider has a section (not Other)", () => {
    for (const n of BACKEND_NAMES) expect(sectionOf(n), n).not.toBe("Other");
  });
  it("no provider is listed twice, and every listed name exists in the backend", () => {
    const all = SECTIONS.flatMap((s) => s.names);
    expect(new Set(all).size).toBe(all.length);
    for (const n of all) expect(BACKEND_NAMES, n).toContain(n);
  });
  it("groupRows puts a header before each section, keeps the original order inside it, and sends unknown names to Other", () => {
    const rows = [{ name: "fred" }, { name: "openai" }, { name: "zzz" }, { name: "openrouter" }];
    const out = groupRows(rows);
    expect(out.map((r) => (isHeaderRow(r) ? `# ${r.header}` : r.name))).toEqual([
      "# AI models", "openai", "openrouter", "# Economic and official data", "fred", "# Other", "zzz",
    ]);
  });
});
