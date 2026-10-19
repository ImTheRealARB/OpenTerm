import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createDrawSaver } from "./drawSave";
import type { Drawing } from "./drawings";

const d = (id: string): Drawing => ({ id, kind: "HLINE", pts: [{ t: 1, p: 2 }] });

describe("drawings saver", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("saves to the symbol the list was loaded for, even after the panel's symbol changed (stale closure bug)", () => {
    const save = vi.fn(() => Promise.resolve());
    const s = createDrawSaver(save, () => {});
    s.loaded("AAPL");
    s.reset(); // the panel switches to MSFT in place
    s.loaded("MSFT");
    s.change([d("d1")]); // a key handler registered while AAPL was shown still calls this
    vi.advanceTimersByTime(400);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("MSFT", [d("d1")]);
  });

  it("flush on a switch saves the old symbol's pending edit to the old symbol", () => {
    const save = vi.fn(() => Promise.resolve());
    const s = createDrawSaver(save, () => {});
    s.loaded("AAPL");
    s.change([d("d1")]);
    s.flush();
    s.reset();
    s.loaded("MSFT");
    vi.advanceTimersByTime(1000);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("AAPL", [d("d1")]);
  });

  it("never saves an edit made before the list loaded, nor over the loaded list later", () => {
    const save = vi.fn(() => Promise.resolve());
    const s = createDrawSaver(save, () => {});
    s.reset();
    s.change([d("early")]);
    vi.advanceTimersByTime(400);
    s.loaded("AAPL");
    s.flush();
    expect(save).not.toHaveBeenCalled();
  });

  it("debounces to one save and reports a failure", async () => {
    const notes: (string | null)[] = [];
    const save = vi.fn(() => Promise.reject({ message: "DISK FULL" }));
    const s = createDrawSaver(save, (n) => notes.push(n));
    s.loaded("AAPL");
    s.change([d("d1")]);
    s.change([d("d1"), d("d2")]);
    vi.advanceTimersByTime(400);
    await Promise.resolve();
    await Promise.resolve();
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("AAPL", [d("d1"), d("d2")]);
    expect(notes).toEqual(["DRAWINGS NOT SAVED: DISK FULL"]);
  });
});
