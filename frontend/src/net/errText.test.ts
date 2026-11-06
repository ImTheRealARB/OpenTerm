import { describe, expect, it } from "vitest";
import { errMessage, errText } from "./errText";

// A stand-in with the same fields as ApiError (the real class lives in core.ts, which needs a browser).
const apiError = (message: string, detail?: string) => Object.assign(new Error(message), { detail });

describe("errText", () => {
  it("shows only the message when the server sent no detail", () => {
    expect(errText(apiError("HTTP 500"))).toBe("HTTP 500");
    expect(errMessage(apiError("HTTP 500", "ignored"))).toBe("HTTP 500");
  });

  it("attaches the detail in parentheses by default and after a colon on request", () => {
    expect(errText(apiError("NOT SAVED", "LINE 3: bad"))).toBe("NOT SAVED (LINE 3: bad)");
    expect(errText(apiError("NOT SAVED", "LINE 3: bad"), "colon")).toBe("NOT SAVED: LINE 3: bad");
  });

  it("copes with things that are not errors", () => {
    expect(errText("boom")).toBe("boom");
    expect(errText(null)).toBe("null");
  });
});
