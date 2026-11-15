import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The runtime keeps one mirror per module load, so each test loads a fresh copy (`vi.resetModules`) over an in-memory
 * localStorage. This is the two-device story end to end without a browser: edit, build the PUT body, merge the answer.
 */
const MIRROR = "openterm.settings";
let store: Map<string, string>;

beforeEach(() => {
  store = new Map();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  });
  vi.resetModules();
});

const load = () => import("./runtime");
const saved = () => JSON.parse(store.get(MIRROR) ?? "null");

describe("settings runtime: per-field times", () => {
  it("an edit stamps only the fields it changed, and the PUT body carries every field's time", async () => {
    const rt = await load();
    rt.updateSettings((s) => ({ ...s, theme: "green" }));
    const { settings, fieldTimes } = rt.pushPayload();
    expect(settings).toMatchObject({ theme: "green", mode: "gui" }); // a brand-new user's gui mode is part of the first save
    expect(fieldTimes.theme).toBeGreaterThan(0);
    expect(fieldTimes.mode).toBeGreaterThan(0); // stamped too: it was not in the (absent) mirror
    expect(fieldTimes.vim).toBe(0); // never set
    expect(saved().fieldTimes.theme).toBe(fieldTimes.theme);
  });

  it("two devices edit different fields: the answer to the second PUT brings the first device's field in", async () => {
    // Device B: edits vim at ~now and holds nothing else. The server already has theme from device A, set earlier.
    const rt = await load();
    rt.updateSettings((s) => ({ ...s, vim: true }));
    const aAt = Date.now() / 1000 - 100;
    const ours = rt.pushPayload().fieldTimes; // the server accepted B's fields (mode and vim) and already held A's theme
    const answer = {
      settings: { mode: "gui", theme: "green", vim: true },
      updated_at: Date.now() / 1000,
      field_times: { theme: aAt, mode: ours.mode, vim: ours.vim },
    };
    expect(rt.mergeRemote(answer)).toBe(false); // nothing of ours is newer than the answer
    expect(rt.getSettings()).toMatchObject({ theme: "green", vim: true }); // A's theme is applied here
    expect(rt.mirrorState().dirty).toBe(false);
    expect(saved().settings).toMatchObject({ theme: "green", vim: true });
  });

  it("an edit made while a PUT is in flight stays dirty after the answer", async () => {
    const rt = await load();
    rt.updateSettings((s) => ({ ...s, theme: "green" }));
    const sent = rt.pushPayload();
    await new Promise((r) => setTimeout(r, 5)); // distinct millisecond for the second edit
    rt.updateSettings((s) => ({ ...s, vim: true })); // edited after the request left
    const answer = { settings: sent.settings, updated_at: Date.now() / 1000 - 1, field_times: sent.fieldTimes };
    expect(rt.mergeRemote(answer)).toBe(true); // vim is newer than the answer: still to push
    expect(rt.mirrorState().dirty).toBe(true);
    expect(rt.getSettings().vim).toBe(true);
  });

  it("a brand-new user with nothing on the backend gets no mirror written (their default mode must stay gui)", async () => {
    const rt = await load();
    expect(rt.mergeRemote({ settings: null, updated_at: null, field_times: {} })).toBe(false);
    expect(store.has(MIRROR)).toBe(false);
  });

  it("an old mirror (no fieldTimes) loads, is pushed with all fields at its time, and gains times on the next edit", async () => {
    store.set(MIRROR, JSON.stringify({ settings: { theme: "white" }, updatedAt: 50, dirty: true }));
    const rt = await load();
    expect(rt.getSettings().theme).toBe("white");
    expect(rt.pushPayload().fieldTimes.theme).toBe(50);
    expect(rt.pushPayload().fieldTimes.vim).toBe(50); // legacy: every field changed when the copy was saved
    rt.updateSettings((s) => ({ ...s, vim: true }));
    const times = rt.pushPayload().fieldTimes;
    expect(times.theme).toBe(50); // untouched fields keep the legacy time
    expect(times.vim).toBeGreaterThan(50);
  });

  it("a reset stamps the reset fields so it wins over an older copy elsewhere", async () => {
    const rt = await load();
    rt.updateSettings((s) => ({ ...s, theme: "green" }));
    await new Promise((r) => setTimeout(r, 5));
    const before = rt.pushPayload().fieldTimes.theme;
    rt.resetSettings();
    const { settings, fieldTimes } = rt.pushPayload();
    expect(settings.theme).toBeUndefined(); // absent = default ...
    expect(fieldTimes.theme).toBeGreaterThan(before); // ... but timed, so the server applies the reset
  });
});
