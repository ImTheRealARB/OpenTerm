/**
 * Workspace templates: four one-click layouts (pure data + pure helpers, so vitest can load it; the TMPL panel and
 * the GUI menu apply them). Every code is a registered function (a test checks). Panels show real data from the
 * normal providers with their usual STALE / ERR / source labels; nothing here is invented.
 */
import type { Layout, View, WorkspaceState } from "../state/workspace";
import { starterWorkspace } from "./starterLayout";

export interface Template {
  /** Command argument: `TMPL MACRO`. */
  id: string;
  label: string;
  about: string;
  views: View[];
}

export const TEMPLATES: readonly Template[] = [
  {
    id: "LONGTERM",
    label: "Long-term investor",
    about: "Company profile, financials, a 5-year chart and news",
    views: [
      { fn: "DES", security: { symbol: "AAPL" }, args: [] },
      { fn: "FA", security: { symbol: "AAPL" }, args: [] },
      { fn: "GP", security: { symbol: "AAPL" }, args: ["5Y"] },
      { fn: "N", args: ["TOP"] },
    ],
  },
  {
    id: "DAY",
    label: "Day trader",
    about: "Intraday 5-minute chart, live watch list, top movers and news",
    views: [
      { fn: "GP", security: { symbol: "SPY" }, args: ["1D", "5MIN"] },
      { fn: "Q", args: ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META"] },
      { fn: "MOV", args: [] },
      { fn: "N", args: ["TOP"] },
    ],
  },
  {
    id: "MACRO",
    label: "Macro",
    about: "Economic calendar, FRED browser, world indices, currencies and commodities",
    views: [
      { fn: "ECO", args: [] },
      { fn: "MACRO", args: [] },
      { fn: "WEI", args: [] },
      { fn: "FX", args: [] },
      { fn: "CMDTY", args: [] },
    ],
  },
  {
    id: "INDIA",
    label: "India",
    about: "Nifty 50 chart, Indian indices and stocks, news, Kite (read-only) status",
    views: [
      { fn: "GP", security: { symbol: "^NSEI" }, args: [] },
      { fn: "Q", args: ["^NSEI", "^BSESN", "^NSEBANK", "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS"] },
      { fn: "N", args: ["TOP"] },
      { fn: "KITE", args: ["STATUS"] },
    ],
  },
];

const ALIAS: Record<string, string> = { LONG: "LONGTERM", INVESTOR: "LONGTERM", DAYTRADER: "DAY", TRADER: "DAY", NIFTY: "INDIA" };

export const templateById = (id: string): Template | undefined => {
  const k = id.trim().toUpperCase().replace(/[^A-Z]/g, "");
  const want = ALIAS[k] ?? k;
  return TEMPLATES.find((t) => t.id === want);
};

/** A column of panels, even stack. */
function stack(ids: number[]): Layout {
  if (ids.length === 1) return { t: "leaf", id: ids[0] };
  return { t: "split", dir: "h", ratio: 1 / ids.length, a: { t: "leaf", id: ids[0] }, b: stack(ids.slice(1)) };
}

/** n panels: left column gets ceil(n/2), right the rest. Ids 1..n in reading order. */
export function templateWorkspace(t: Template): WorkspaceState {
  const ids = t.views.map((_, i) => i + 1);
  const half = Math.ceil(ids.length / 2);
  const panels: WorkspaceState["panels"] = {};
  ids.forEach((id, i) => {
    panels[id] = { id, views: [t.views[i]], pos: 0 };
  });
  return {
    layout: { t: "split", dir: "v", ratio: 0.5, a: stack(ids.slice(0, half)), b: stack(ids.slice(half)) },
    panels,
    focus: 1,
    maximized: null,
  };
}

/** The view a panel showed before TMPL took it over (TMPL itself does not count as a change). */
const viewBeforeTmpl = (p: WorkspaceState["panels"][number]): View | undefined => {
  let i = p.pos;
  while (i >= 0 && p.views[i]?.fn === "TMPL") i--;
  return p.views[i];
};

const sig = (s: WorkspaceState) =>
  JSON.stringify(
    Object.values(s.panels)
      .sort((a, b) => a.id - b.id)
      .map((p) => {
        const v = viewBeforeTmpl(p) ?? { args: [] };
        return [v.fn ?? "", v.security?.symbol ?? "", v.args];
      }),
  );

/** True when applying a template needs no confirmation: the untouched starter layout, or a lone HELP/TMPL/empty panel. */
export function isReplaceable(s: WorkspaceState): boolean {
  const ids = Object.keys(s.panels);
  if (ids.length === 1) {
    const p = s.panels[Number(ids[0])];
    const v = viewBeforeTmpl(p);
    return !v || !v.fn || v.fn === "HELP";
  }
  return sig(s) === sig(starterWorkspace());
}
