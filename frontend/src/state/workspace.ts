import type { SecurityRef } from "../command/markets";
import { MAX_PANELS } from "./layoutState";
import { memResetAll } from "./panelMemory";
import { createStore, loadJSON, saveJSON } from "./store";

export interface View {
  fn?: string;
  security?: SecurityRef;
  args: string[];
  /** Data source pinned for this view by `SRC=<name>` (lower case, as the API spells it). Absent = the default hierarchy. */
  source?: string;
}

export interface PanelState {
  id: number;
  /** Navigation history; `pos` points at the current view. */
  views: View[];
  pos: number;
}

export type Layout =
  | { t: "leaf"; id: number }
  | { t: "split"; dir: "v" | "h"; ratio: number; a: Layout; b: Layout };

export interface WorkspaceState {
  layout: Layout;
  panels: Record<number, PanelState>;
  focus: number;
  maximized: number | null;
  /** Named layout this workspace was last saved as or loaded from (Ctrl+S re-saves it). */
  name?: string;
}

const KEY = "openterm.workspace";

const initial: WorkspaceState = {
  layout: { t: "leaf", id: 1 },
  panels: { 1: { id: 1, views: [{ fn: "HELP", args: [] }], pos: 0 } },
  focus: 1,
  maximized: null,
};

export const workspace = createStore<WorkspaceState>(loadJSON(KEY, initial));
workspace.subscribe(() => saveJSON(KEY, workspace.get()));

export const currentView = (p: PanelState): View => p.views[p.pos] ?? { args: [] };

function leafIds(l: Layout, out: number[] = []): number[] {
  if (l.t === "leaf") out.push(l.id);
  else {
    leafIds(l.a, out);
    leafIds(l.b, out);
  }
  return out;
}

export const panelOrder = (s: WorkspaceState) => leafIds(s.layout);

function mapLeaf(l: Layout, id: number, f: (leaf: Layout) => Layout): Layout {
  if (l.t === "leaf") return l.id === id ? f(l) : l;
  return { ...l, a: mapLeaf(l.a, id, f), b: mapLeaf(l.b, id, f) };
}

function removeLeaf(l: Layout, id: number): Layout | null {
  if (l.t === "leaf") return l.id === id ? null : l;
  const a = removeLeaf(l.a, id);
  const b = removeLeaf(l.b, id);
  if (!a) return b;
  if (!b) return a;
  return { ...l, a, b };
}

/** Splits the focused panel. Returns the new panel id, or null at the 9-panel cap. */
export function split(dir: "v" | "h"): number | null {
  let newId: number | null = null;
  workspace.set((s) => {
    const used = new Set(Object.keys(s.panels).map(Number));
    if (used.size >= MAX_PANELS) return s;
    let id = 1;
    while (used.has(id)) id++;
    newId = id;
    const src = currentView(s.panels[s.focus]);
    return {
      ...s,
      maximized: null,
      layout: mapLeaf(s.layout, s.focus, (leaf) => ({ t: "split", dir, ratio: 0.5, a: leaf, b: { t: "leaf", id } })),
      panels: { ...s.panels, [id]: { id, views: [{ security: src.security, args: [] }], pos: 0 } },
      focus: id,
    };
  });
  return newId;
}

/**
 * `split`, but at the panel cap it also tells the user (through `say`, e.g. the status bar's `info` or `fail`) instead of
 * failing silently. Every place that splits (keys, menus, the command line) goes through this, so the wording and the
 * limit come from MAX_PANELS in one spot. Returns the new panel id, or null at the cap.
 */
export function splitOrSay(dir: "v" | "h", say: (text: string) => void): number | null {
  const id = split(dir);
  if (id === null) say(`PANEL LIMIT (${MAX_PANELS}) REACHED`);
  return id;
}

export function closePanel(id = workspace.get().focus): void {
  workspace.set((s) => {
    const order = panelOrder(s);
    if (order.length === 1) {
      return { ...s, panels: { [id]: { id, views: [{ args: [] }], pos: 0 } }, maximized: null };
    }
    const layout = removeLeaf(s.layout, id)!;
    const panels = { ...s.panels };
    delete panels[id];
    const idx = order.indexOf(id);
    const remaining = panelOrder({ ...s, layout });
    const focus = s.focus === id ? remaining[Math.min(idx, remaining.length - 1)] : s.focus;
    return { ...s, layout, panels, focus, maximized: s.maximized === id ? null : s.maximized };
  });
}

export function focusPanel(id: number): boolean {
  if (!workspace.get().panels[id]) return false;
  workspace.set((s) => (s.focus === id ? s : { ...s, focus: id, maximized: s.maximized ? id : null }));
  return true;
}

export function cyclePanel(dir: 1 | -1): void {
  const s = workspace.get();
  const order = panelOrder(s);
  const i = order.indexOf(s.focus);
  focusPanel(order[(i + dir + order.length) % order.length]);
}

export function toggleMaximize(): void {
  workspace.set((s) => ({ ...s, maximized: s.maximized ? null : s.focus }));
}

/** Grows/shrinks the focused panel by moving the nearest enclosing split of the matching axis. */
export function resizeFocused(dir: "left" | "right" | "up" | "down", step = 0.05): void {
  const axis = dir === "left" || dir === "right" ? "v" : "h";
  const delta = dir === "right" || dir === "down" ? step : -step;
  workspace.set((s) => {
    let changed = false;
    const walk = (l: Layout): Layout => {
      if (l.t === "leaf") return l;
      const inA = leafIds(l.a).includes(s.focus);
      const inB = !inA && leafIds(l.b).includes(s.focus);
      if (!inA && !inB) return l;
      const child = inA ? walk(l.a) : walk(l.b);
      if (changed) return inA ? { ...l, a: child } : { ...l, b: child };
      if (l.dir !== axis) return inA ? { ...l, a: child } : { ...l, b: child };
      changed = true;
      return { ...l, ratio: Math.min(0.9, Math.max(0.1, l.ratio + delta)) };
    };
    const layout = walk(s.layout);
    return changed ? { ...s, layout } : s;
  });
}

/** Replaces the whole workspace (layout load). AI/SWARM panel memory is reset first: a panel that
 *  lands on an id which held a chat before must start empty, not show someone else's turns. */
export function applyLayout(next: WorkspaceState): void {
  memResetAll();
  workspace.set(() => next);
}

export function setLayoutName(name: string | undefined): void {
  workspace.set((s) => (s.name === name ? s : { ...s, name }));
}

export function navigate(id: number, view: View): void {
  workspace.set((s) => {
    const p = s.panels[id];
    const views = [...p.views.slice(0, p.pos + 1), view].slice(-50);
    return { ...s, focus: id, panels: { ...s.panels, [id]: { id, views, pos: views.length - 1 } } };
  });
}

/** Updates the panel's current view in place (timeframe switch, list edit): no history entry. */
export function replaceView(id: number, update: (v: View) => View): void {
  workspace.set((s) => {
    const p = s.panels[id];
    if (!p) return s;
    const views = p.views.slice();
    views[p.pos] = update(views[p.pos] ?? { args: [] });
    return { ...s, panels: { ...s.panels, [id]: { ...p, views } } };
  });
}

/** Jumps a panel to one entry of its history (window-frame RECENT menu). */
export function historyGo(id: number, pos: number): void {
  workspace.set((s) => {
    const p = s.panels[id];
    if (!p || pos < 0 || pos >= p.views.length || pos === p.pos) return s;
    return { ...s, panels: { ...s.panels, [id]: { ...p, pos } } };
  });
}

export function historyStep(dir: -1 | 1): void {
  workspace.set((s) => {
    const p = s.panels[s.focus];
    const pos = p.pos + dir;
    if (pos < 0 || pos >= p.views.length) return s;
    return { ...s, panels: { ...s.panels, [p.id]: { ...p, pos } } };
  });
}
