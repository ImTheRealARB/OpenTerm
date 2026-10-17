import { describe, expect, it } from "vitest";
import { parseJobsArgs } from "./jobsArgs";

describe("JOBS args", () => {
  it("bare JOBS shows the panel", () => expect(parseJobsArgs([])).toEqual({ kind: "none" }));
  it("TEST defaults to 20 steps of 100 ms", () => expect(parseJobsArgs(["TEST"])).toEqual({ kind: "test", steps: 20, step_ms: 100 }));
  it("TEST steps ms", () => expect(parseJobsArgs(["test", "5", "0"])).toEqual({ kind: "test", steps: 5, step_ms: 0 }));
  it("rejects junk", () => {
    expect(parseJobsArgs(["FOO"]).kind).toBe("error");
    expect(parseJobsArgs(["TEST", "x"]).kind).toBe("error");
    expect(parseJobsArgs(["TEST", "0"]).kind).toBe("error");
    expect(parseJobsArgs(["TEST", "5", "10", "1"]).kind).toBe("error");
  });
});
