/** Open/close state of the window-frame menu and the code that carries out a picked item. */
import { info } from "../command/status";
import { FUNCTIONS } from "../functions/registry";
import { exportPanelCsv } from "../functions/tableExport";
import { dispatchPanelKey } from "../keys/panelKeys";
import { createStore } from "../state/store";
import { closePanel, currentView, focusPanel, historyGo, navigate, split, toggleMaximize, workspace } from "../state/workspace";
import { menuItems, menuKey, type FnInfo, type MenuIndex, type MenuItem, type MenuState } from "./windowMenu";

export const windowMenu = createStore<MenuState | null>(null);

export const FN_INFO: FnInfo = {
  isBuilt: (code) => !!FUNCTIONS.get(code)?.load,
  title: (code) => FUNCTIONS.get(code)?.title ?? code,
};

export function openWindowMenu(panel = workspace.get().focus, menu: MenuIndex = 0): void {
  focusPanel(panel);
  windowMenu.set(() => ({ panel, menu, sel: 0 }));
}

export const closeWindowMenu = () => windowMenu.set(() => null);

export function itemsOf(state: MenuState): MenuItem[] {
  const p = workspace.get().panels[state.panel];
  return p ? menuItems(state.menu, p, FN_INFO) : [];
}

export function runItem(panel: number, item: MenuItem): void {
  closeWindowMenu();
  focusPanel(panel);
  if (item.kind === "history") return historyGo(panel, item.pos);
  if (item.kind === "fn") {
    const p = workspace.get().panels[panel];
    return navigate(panel, { fn: item.fn, security: p ? currentView(p).security : undefined, args: [] });
  }
  switch (item.action) {
    case "maximize":
      return toggleMaximize();
    case "splitVertical":
    case "splitHorizontal":
      if (split(item.action === "splitVertical" ? "v" : "h") === null) info("PANEL LIMIT (9) REACHED");
      return;
    case "refresh":
      if (!dispatchPanelKey(panel, new KeyboardEvent("keydown", { key: "F5" }))) info("NOTHING TO REFRESH IN THIS PANEL");
      return;
    case "exportCsv":
      exportPanelCsv(panel);
      return;
    case "closePanel":
      return closePanel(panel);
  }
}

/** Keyboard handling while a menu is open. Returns true when the key was used; any other key closes the menu. */
export function windowMenuKey(e: KeyboardEvent): boolean {
  const state = windowMenu.get();
  if (!state) return false;
  if (e.ctrlKey || e.altKey || e.metaKey || ["Shift", "Control", "Alt", "Meta"].includes(e.key)) return false;
  const items = itemsOf(state);
  const r = menuKey(state, e.key, items.length);
  if (!r) {
    closeWindowMenu();
    return false;
  }
  if (r.pick !== undefined) runItem(state.panel, items[r.pick]);
  else windowMenu.set(() => r.state);
  return true;
}
