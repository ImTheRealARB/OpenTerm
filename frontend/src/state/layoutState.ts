/**
 * Saved layouts: what goes into SQLite and the checks a loaded one must pass before it replaces
 * the workspace. Pure functions (no store, no network) so they are unit-tested directly.
 */
import type { Layout, PanelState, View, WorkspaceState } from "./workspace";

export const MAX_PANELS = 9;
export const LAYOUT_NAME_RE = /^[A-Z0-9][A-Z0-9_.-]{0,31}$/;

/** A layout is a template: each panel keeps only its current view, not its back/forward history. */
export function snapshot(s: WorkspaceState): Omit<WorkspaceState, "name"> {
  const panels: Record<number, PanelState> = {};
  for (const [id, p] of Object.entries(s.panels)) {
    const v = p.views[p.pos] ?? { args: [] };
    panels[Number(id)] = { id: p.id, views: [v], pos: 0 };
  }
  return { layout: s.layout, panels, focus: s.focus, maximized: s.maximized };
}

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

function parseTree(x: unknown, ids: number[], depth: number): Layout | null {
  if (!isObj(x) || depth > MAX_PANELS) return null;
  if (x.t === "leaf") {
    const id = x.id;
    if (typeof id !== "number" || !Number.isInteger(id) || id < 1 || id > MAX_PANELS || ids.includes(id)) return null;
    ids.push(id);
    return { t: "leaf", id };
  }
  if (x.t !== "split" || (x.dir !== "v" && x.dir !== "h")) return null;
  const a = parseTree(x.a, ids, depth + 1);
  const b = a && parseTree(x.b, ids, depth + 1);
  if (!a || !b) return null;
  const ratio = typeof x.ratio === "number" && Number.isFinite(x.ratio) ? Math.min(0.9, Math.max(0.1, x.ratio)) : 0.5;
  return { t: "split", dir: x.dir, ratio, a, b };
}

function parseView(x: unknown, isFunction: (code: string) => boolean): View {
  if (!isObj(x)) return { args: [] };
  const args = Array.isArray(x.args) ? x.args.filter((a): a is string => typeof a === "string").slice(0, 50) : [];
  const fn = typeof x.fn === "string" && isFunction(x.fn) ? x.fn : undefined;
  const sec = isObj(x.security) && typeof x.security.symbol === "string" ? x.security : null;
  const security = sec
    ? { symbol: sec.symbol as string, ...(typeof sec.market === "string" ? { market: sec.market } : {}) }
    : undefined;
  return { ...(fn ? { fn } : {}), ...(security ? { security } : {}), args };
}

/**
 * Validates a layout from storage. Returns null when the panel tree is unusable. Unknown functions
 * (from a newer or older version) become empty views instead of failing the whole layout.
 */
export function parseLayout(x: unknown, isFunction: (code: string) => boolean): WorkspaceState | null {
  if (!isObj(x) || !isObj(x.panels)) return null;
  const ids: number[] = [];
  const layout = parseTree(x.layout, ids, 0);
  if (!layout) return null;
  const panels: Record<number, PanelState> = {};
  for (const id of ids) {
    const p = x.panels[id];
    const raw = isObj(p) && Array.isArray(p.views) ? p.views : [];
    const pos = isObj(p) && typeof p.pos === "number" && raw[p.pos] !== undefined ? p.pos : raw.length - 1;
    panels[id] = { id, views: [parseView(raw[pos], isFunction)], pos: 0 };
  }
  const focus = typeof x.focus === "number" && ids.includes(x.focus) ? x.focus : ids[0];
  const maximized = typeof x.maximized === "number" && ids.includes(x.maximized) ? x.maximized : null;
  return { layout, panels, focus, maximized };
}
