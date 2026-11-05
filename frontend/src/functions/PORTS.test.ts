import { describe, expect, it } from "vitest";
import { fmtTons, headline, portLabel, queryArg } from "./portsFormat";
import { FUNCTIONS } from "./registry";

describe("PORTS registry entry", () => {
  it("is registered with a loader", () => {
    const def = FUNCTIONS.get("PORTS");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
  });
});

describe("portsFormat", () => {
  it("joins the words after PORTS and trims them", () => {
    expect(queryArg([])).toBe("");
    expect(queryArg(["port", "said"])).toBe("port said");
    expect(queryArg(["  japan "])).toBe("japan");
  });

  it("shows tonnage compactly and leaves unknown values blank", () => {
    expect(fmtTons(null)).toBe("");
    expect(fmtTons(950)).toBe("950");
    expect(fmtTons(412_300)).toBe("412k");
    expect(fmtTons(9_678_917)).toBe("9.68M");
    expect(fmtTons(1_234_000_000)).toBe("1.23B");
  });

  it("labels a port with its country when known", () => {
    expect(portLabel("Rotterdam", "The Netherlands")).toBe("Rotterdam, The Netherlands");
    expect(portLabel("Rotterdam", null)).toBe("Rotterdam");
  });

  it("describes what is on screen", () => {
    expect(headline("top", "", 25)).toBe("25 BUSIEST PORTS, LAST 7 DAYS ON RECORD");
    expect(headline("search", "japan", 1)).toBe('1 PORT MATCHING "JAPAN"');
    expect(headline("search", "japan", 20)).toBe('20 PORTS MATCHING "JAPAN"');
  });
});
