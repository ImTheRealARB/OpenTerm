/**
 * Window-frame menus (RECENT, RELATED, OPTIONS) in each panel's title bar. Pure: builds the item
 * lists and moves the cursor; `windowMenuRun.ts` carries out a picked item. Unit-tested in Node.
 */
import type { PanelState, View } from "../state/workspace";

export const MENUS = ["RECENT", "RELATED", "OPTIONS"] as const;
export type MenuIndex = 0 | 1 | 2;

export type OptionAction = "maximize" | "splitVertical" | "splitHorizontal" | "refresh" | "exportCsv" | "closePanel";

export type MenuItem =
  | { kind: "history"; pos: number; label: string; current: boolean }
  | { kind: "fn"; fn: string; label: string }
  | { kind: "action"; action: OptionAction; label: string };

export const OPTIONS: { action: OptionAction; label: string }[] = [
  { action: "maximize", label: "MAXIMIZE / RESTORE" },
  { action: "splitVertical", label: "SPLIT VERTICAL" },
  { action: "splitHorizontal", label: "SPLIT HORIZONTAL" },
  { action: "refresh", label: "REFRESH" },
  { action: "exportCsv", label: "EXPORT CSV" },
  { action: "closePanel", label: "CLOSE PANEL" },
];

export const viewLabel = (v: View): string => [v.security?.symbol, v.fn ?? "EMPTY", ...v.args].filter(Boolean).join(" ");

/** Lookups the caller supplies, so this module stays free of the function registry. */
export interface FnInfo {
  isBuilt(code: string): boolean;
  title(code: string): string;
  /** Codes offered by RELATED, in order: the security list when the panel has a security, else the market list (the registry's `related` ranks). */
  related(withSecurity: boolean): readonly string[];
}

export function menuItems(menu: MenuIndex, panel: PanelState, info: FnInfo): MenuItem[] {
  if (menu === 0) {
    const out: MenuItem[] = [];
    for (let pos = panel.views.length - 1; pos >= 0; pos--) out.push({ kind: "history", pos, label: viewLabel(panel.views[pos]), current: pos === panel.pos });
    return out;
  }
  if (menu === 1) {
    const view = panel.views[panel.pos];
    const list = info.related(!!view?.security);
    return list
      .filter((code) => code !== view?.fn && info.isBuilt(code))
      .map((fn) => ({ kind: "fn", fn, label: `${fn.padEnd(6)} ${info.title(fn).toUpperCase()}` }));
  }
  return OPTIONS.map((o) => ({ kind: "action", ...o }));
}

export interface MenuState {
  panel: number;
  menu: MenuIndex;
  sel: number;
}

export type MenuKeyResult = { state: MenuState | null; pick?: number } | null;

/**
 * Applies one key to an open menu. Returns null when the key is not the menu's (let it pass),
 * otherwise the next state (null = closed) and, for Enter or a digit, the picked item index.
 */
export function menuKey(state: MenuState, key: string, count: number): MenuKeyResult {
  const switchTo = (menu: number): MenuKeyResult => ({ state: { ...state, menu: (((menu % 3) + 3) % 3) as MenuIndex, sel: 0 } });
  switch (key) {
    case "Escape":
      return { state: null };
    case "ArrowLeft":
      return switchTo(state.menu - 1);
    case "ArrowRight":
      return switchTo(state.menu + 1);
    case "ArrowDown":
    case "j":
      return { state: { ...state, sel: count ? (state.sel + 1) % count : 0 } };
    case "ArrowUp":
    case "k":
      return { state: { ...state, sel: count ? (state.sel - 1 + count) % count : 0 } };
    case "Enter":
      return count ? { state: null, pick: state.sel } : { state };
  }
  if (/^[1-9]$/.test(key)) {
    const i = Number(key) - 1;
    return i < count ? { state: null, pick: i } : { state };
  }
  return null;
}
