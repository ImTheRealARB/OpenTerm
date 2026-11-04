import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { retryDelayMs, sendWithRetry } from "./triggerRetry";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("sendWithRetry (audit 2026-11-04 #2)", () => {
  it("retries a rejected trigger POST until it succeeds, then stops", async () => {
    const send = vi.fn().mockRejectedValueOnce(new Error("503")).mockRejectedValueOnce(new Error("503")).mockResolvedValue({});
    const onDone = vi.fn();
    const onFail = vi.fn();
    sendWithRetry(send, { stillWanted: () => true, onDone, onFail });
    await vi.advanceTimersByTimeAsync(0);
    expect(send).toHaveBeenCalledTimes(1);
    expect(onFail).toHaveBeenCalledWith(expect.any(Error), 1);
    await vi.advanceTimersByTimeAsync(retryDelayMs(1));
    expect(send).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(retryDelayMs(2));
    expect(send).toHaveBeenCalledTimes(3);
    expect(onDone).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(send).toHaveBeenCalledTimes(3); // no double report after success
  });

  it("stops when the alert is no longer firing (deleted or re-armed)", async () => {
    let wanted = true;
    const send = vi.fn().mockRejectedValue(new Error("down"));
    sendWithRetry(send, { stillWanted: () => wanted, onDone: vi.fn(), onFail: vi.fn() });
    await vi.advanceTimersByTimeAsync(0);
    wanted = false;
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("backs off and caps at 60 s", () => {
    expect([1, 2, 3, 4, 5, 9].map(retryDelayMs)).toEqual([2_000, 5_000, 15_000, 30_000, 60_000, 60_000]);
  });
});
