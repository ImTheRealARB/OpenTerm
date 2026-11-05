import { describe, expect, it } from "vitest";
import { bareSecurityFn } from "./bareSecurity";

// Stand-in for the registry: only GP and FA take a security here.
const needs = (code: string) => code === "GP" || code === "FA";

describe("bareSecurityFn: which function a bare ticker opens", () => {
  it("terminal mode (no keepFn) always opens DES, whatever the panel shows", () => {
    expect(bareSecurityFn(undefined, "GP", needs)).toBe("DES");
    expect(bareSecurityFn(false, "GP", needs)).toBe("DES");
  });
  it("GUI mode keeps the panel's function when that function takes a security", () => {
    expect(bareSecurityFn(true, "GP", needs)).toBe("GP");
    expect(bareSecurityFn(true, "FA", needs)).toBe("FA");
  });
  it("GUI mode still opens DES when the panel's function takes no security (news, help, watchlist)", () => {
    expect(bareSecurityFn(true, "N", needs)).toBe("DES");
    expect(bareSecurityFn(true, "HELP", needs)).toBe("DES");
  });
  it("GUI mode opens DES in a brand-new empty panel (it has no function yet)", () => {
    expect(bareSecurityFn(true, undefined, needs)).toBe("DES");
  });
});
