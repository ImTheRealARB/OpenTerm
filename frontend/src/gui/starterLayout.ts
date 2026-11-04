/**
 * First screen for a brand-new GUI user: three panels instead of one empty "help" panel.
 *
 *   left   a quote monitor (Q) of six large US stocks      <- panel 1, the focused one
 *   right  a chart of the S&P 500 ETF (GP SPY), over the top news (N TOP)
 *
 * All three show real data from the normal providers (and their usual STALE / ERR / source labels). Nothing is
 * invented here, and it is a plain saved layout: the user can close or change any panel like any other.
 *
 * It only applies when nothing was ever saved (no `openterm.workspace` in localStorage) and the workspace is still
 * the untouched one-panel start screen. Terminal mode never calls it, and a user with a saved layout is left alone.
 */
import { workspace, type WorkspaceState } from "../state/workspace";

const WORKSPACE_KEY = "openterm.workspace";

/** The starter layout as a workspace value (pure, so a unit test can check it). */
export function starterWorkspace(): WorkspaceState {
  return {
    // "v" splits side by side (left | right), "h" stacks (top over bottom).
    layout: {
      t: "split",
      dir: "v",
      ratio: 0.4,
      a: { t: "leaf", id: 1 },
      b: { t: "split", dir: "h", ratio: 0.6, a: { t: "leaf", id: 2 }, b: { t: "leaf", id: 3 } },
    },
    panels: {
      1: { id: 1, views: [{ fn: "Q", args: ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "TSLA"] }], pos: 0 },
      2: { id: 2, views: [{ fn: "GP", security: { symbol: "SPY" }, args: [] }], pos: 0 },
      3: { id: 3, views: [{ fn: "N", args: ["TOP"] }], pos: 0 },
    },
    focus: 1,
    maximized: null,
  };
}

/** True when the saved workspace is missing and the current one is the untouched start screen. */
function isFreshWorkspace(): boolean {
  try {
    if (localStorage.getItem(WORKSPACE_KEY) !== null) return false;
  } catch {
    return false; // storage blocked: we cannot tell, so leave the workspace alone
  }
  const s = workspace.get();
  const ids = Object.keys(s.panels);
  if (ids.length !== 1) return false;
  const p = s.panels[Number(ids[0])];
  return p.views.length === 1 && p.views[0].fn === "HELP";
}

/** Applies the starter layout for a new user. Returns true when it did. */
export function applyStarterLayoutIfNew(): boolean {
  if (!isFreshWorkspace()) return false;
  workspace.set(() => starterWorkspace());
  return true;
}
