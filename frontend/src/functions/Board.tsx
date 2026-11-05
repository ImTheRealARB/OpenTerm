/** A fixed, sectioned live board (WEI, FX, CMDTY): REST snapshot, then streamed ticks. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtChg, fmtPct, fmtPrice, fmtRate, fmtTime } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { navigate } from "../state/workspace";
import type { BoardDef } from "./boards";
import { chg, dirColor, guiTitle, high, low, lastColor, lastFlash, navKey, pct, price, quoteTime, srcColor, srcText, useLatest, useLiveRows, useQuotes, type QRow } from "./quoteRows";
import { QuoteErrors } from "./QuoteErrors";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

interface BRow extends QRow {
  label: string;
  unit?: string;
  /** Set on section header rows (no symbol). */
  section?: string;
}

const isHeader = (r: BRow | undefined) => !!r?.section;
const liveOf = (r: BRow) => (r.section || r.error ? undefined : r.symbol);

function columns(def: BoardDef, gui = false): Column<BRow>[] {
  const num = def.rates ? fmtRate : fmtPrice;
  const signed = (v: number | null) => (v == null ? fmtChg(v) : (v > 0 ? "+" : "") + num(v));
  const cols: Column<BRow>[] = [
    { title: "NAME", width: 20, text: (r) => r.section ?? r.label, color: () => "fg" },
    { title: "SECURITY", width: 11, text: (r) => r.symbol, color: (r) => (r.error ? "err" : "dim") },
    { title: "SRC", width: 9, text: srcText, color: srcColor },
    { title: "LAST", width: 12, align: "right", text: (r) => num(price(r)), color: lastColor, flash: lastFlash },
    { title: "CHG", width: 10, align: "right", text: (r) => signed(chg(r)), color: (r) => dirColor(chg(r)) },
    { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(pct(r)), color: (r) => dirColor(pct(r)) },
    { title: "HIGH", width: 11, align: "right", text: (r) => num(high(r)) },
    { title: "LOW", width: 11, align: "right", text: (r) => num(low(r)) },
    { title: "TIME", width: 8, align: "right", text: (r) => fmtTime(quoteTime(r)) },
  ];
  if (def.sections.some((s) => s.items.some((i) => i.unit))) cols.push({ title: "UNIT", width: 9, text: (r) => r.unit ?? "", color: () => "dim" });
  // GUI mode: the numbers a beginner wants come first (NAME, LAST, CHG, %CHG) so %CHG is never clipped at the panel edge,
  // and SRC (the data source) moves to the far right. The error text rides in the SECURITY column there.
  if (gui) {
    const by = (t: string) => cols.find((c) => c.title === t)!;
    const order = ["NAME", "LAST", "CHG", "%CHG", "SECURITY", "HIGH", "LOW", "TIME", "SRC"];
    const rest = cols.filter((c) => !order.includes(c.title));
    cols.splice(0, cols.length, ...order.map((t) => (t === "SECURITY" ? { ...by(t), width: 16 } : by(t))), ...rest);
  }
  const errCol = gui ? "SECURITY" : "SRC";
  // Header rows show only their title; errors replace the numbers on their own row.
  return cols.map((c, i) => ({
    ...c,
    // GUI: plain-word header (Ticker, Price, Change ...) and a column at least as wide as it. `c.title` stays the code for the checks below.
    title: gui ? guiTitle(c.title) : c.title,
    width: gui ? Math.max(c.width, guiTitle(c.title).length + 1) : c.width,
    text: (r) => (r.section ? (i === 0 ? r.section : "") : r.error && c.title === errCol ? r.error : c.text(r)),
    color: (r) => (r.error && c.title === errCol ? "err" : (c.color?.(r) ?? "fg")),
  }));
}

export function Board({ panelId, def }: FunctionProps & { def: BoardDef }) {
  const inputs = useMemo(() => def.sections.flatMap((s) => s.items.map((i) => i.symbol)), [def]);
  const gui = useStore(settingsStore, (st) => st.mode === "gui");
  const cols = useMemo(() => columns(def, gui), [def, gui]);
  const [reload, setReload] = useState(0);
  const { rows: quotes, loading } = useQuotes(inputs, reload);
  const grid = useRef<GridHandle>(null);

  const rows = useMemo(() => {
    const by = new Map(quotes.map((q) => [q.input, q]));
    const out: BRow[] = [];
    for (const s of def.sections) {
      out.push({ input: "", symbol: "", label: "", section: s.title, fetchedAt: 0, ageAtFetch: 0 });
      for (const it of s.items) out.push({ ...(by.get(it.symbol) ?? { input: it.symbol, symbol: it.symbol, fetchedAt: 0, ageAtFetch: 0 }), label: it.label, unit: it.unit });
    }
    return out;
  }, [quotes, def]);
  const latest = useLatest(rows);
  useCsvExport(panelId, () => gridCsv(def.code, cols, rows.filter((r) => !r.section)));

  useLiveRows(rows, grid, liveOf);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.length, (i) => isHeader(cur[i]))) return true;
        switch (e.key) {
          case "Enter": {
            const r = cur[g?.selected() ?? -1];
            if (r && !r.section) navigate(panelId, { fn: "GP", security: { symbol: r.symbol }, args: [] });
            return true;
          }
          case "F5":
            setReload((n) => n + 1);
            return true;
        }
        return false;
      }),
    [panelId, def, cols, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">{def.title}</span> <b className="pv">{inputs.length}</b> {def.noun}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim legend"> · J/K MOVE · ENTER CHART · E CSV · F5 REFRESH</span>
      </div>
      <QuoteErrors rows={rows.filter((r) => !r.section)} onRetry={() => setReload((n) => n + 1)} />
      <Grid ref={grid} columns={cols} rows={rows} initialSelected={1} band={isHeader} />
    </div>
  );
}
