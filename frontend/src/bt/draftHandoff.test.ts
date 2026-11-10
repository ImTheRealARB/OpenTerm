import { describe, expect, it } from "vitest";
import { setPendingDraft, takePendingDraft } from "./draftHandoff";

describe("draftHandoff", () => {
  it("gives the draft to the editor of that name once", () => {
    setPendingDraft("my_cross", "class SignalEngine: ...");
    expect(takePendingDraft("other")).toBeNull();
    expect(takePendingDraft("my_cross")).toBe("class SignalEngine: ...");
    expect(takePendingDraft("my_cross")).toBeNull();
  });
});
