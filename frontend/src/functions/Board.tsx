/** A fixed, sectioned live board (WEI, FX, CMDTY): REST snapshot, then streamed ticks. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtChg, fmtPct, fmtPrice, fmtRate, fmtTime } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { navigate } from "../state/workspace";
import type { BoardDef } from "./boards";
import { chg, dirColor, guiTitle, high, low, lastColor, lastFlash, pct, price, quoteTime, srcColor, srcText, useLiveRows, useQuotes, type QRow } from "./quoteRows";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import { QuoteErrors } from "./QuoteErrors";
import { drawChangeBar, drawSpark, flagColor, flagText, type SparkRow } from "./boardGraphics";
import { useSparks } from "./useSparks";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

interface BRow extends QRow, SparkRow {
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
  const col = {
    name: { title: "NAME", width: 20, text: (r) => r.section ?? r.label, color: () => "fg" },
    security: { title: "SECURITY", width: 11, text: (r) => r.symbol, color: (r) => (r.error ? "err" : "dim") },
    src: { title: "SRC", width: 9, text: srcText, color: srcColor },
    last: { title: "LAST", width: 12, align: "right", text: (r) => num(price(r)), color: lastColor, flash: lastFlash },
    // One-letter data status after the last value: d = delayed, c = close, blank = real time or unknown (rules: components/microGraphics.ts).
    flag: { title: "", width: 1, aux: true, text: flagText, color: flagColor },
    chg: { title: "CHG", width: 10, align: "right", text: (r) => signed(chg(r)), color: (r) => dirColor(chg(r)) },
    pct: { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(pct(r)), color: (r) => dirColor(pct(r)) },
    // The change bar and the 2DAY sparkline are drawn on the canvas (Column.draw); their text is empty and `aux` keeps them out of .sr and CSV.
    bar: { title: "", width: 7, aux: true, text: () => "", draw: drawChangeBar },
    spark: { title: "2DAY", width: 9, aux: true, text: () => "", draw: drawSpark },
    high: { title: "HIGH", width: 11, align: "right", text: (r) => num(high(r)) },
    low: { title: "LOW", width: 11, align: "right", text: (r) => num(low(r)) },
    time: { title: "TIME", width: 8, align: "right", text: (r) => fmtTime(quoteTime(r)) },
  } satisfies Record<string, Column<BRow>>;
  const unit: Column<BRow>[] = def.sections.some((s) => s.items.some((i) => i.unit))
    ? [{ title: "UNIT", width: 9, text: (r) => r.unit ?? "", color: () => "dim" }]
    : [];
  // Terminal order. GUI mode: the numbers a beginner wants come first (NAME, LAST, CHG, %CHG) so %CHG is never clipped at the panel edge,
  // and SRC (the data source) moves to the far right. The error text rides in the SECURITY column there.
  const cols: Column<BRow>[] = gui
    ? [col.name, col.last, col.flag, col.chg, col.pct, col.bar, col.spark, { ...col.security, width: 16 }, col.high, col.low, col.time, col.src, ...unit]
    : [col.name, col.security, col.src, col.last, col.flag, col.chg, col.pct, col.bar, col.spark, col.high, col.low, col.time, ...unit];
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
  const sparks = useSparks(inputs, reload);
  const grid = useRef<GridHandle>(null);

  const rows = useMemo(() => {
    const by = new Map(quotes.map((q) => [q.input, q]));
    const out: BRow[] = [];
    for (const s of def.sections) {
      out.push({ input: "", symbol: "", label: "", section: s.title, fetchedAt: 0, ageAtFetch: 0 });
      for (const it of s.items) out.push({ ...(by.get(it.symbol) ?? { input: it.symbol, symbol: it.symbol, fetchedAt: 0, ageAtFetch: 0 }), label: it.label, unit: it.unit, spark: sparks.by[it.symbol] });
    }
    return out;
  }, [quotes, def, sparks]);
  const latest = useLatest(rows);
  useCsvExport(panelId, () => gridCsv(def.code, cols.filter((c) => !c.aux), rows.filter((r) => !r.section)));

  useLiveRows(rows, grid, liveOf);

  usePanelRefresh(panelId, () => { setReload((n) => n + 1); });
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
        {sparks.error && <span className="warn"> · 2DAY LINES: {sparks.error}</span>}
        <span className="dim legend"> · J/K MOVE · ENTER CHART · E CSV · F5 REFRESH</span>
      </div>
      <QuoteErrors rows={rows.filter((r) => !r.section)} onRetry={() => setReload((n) => n + 1)} />
      <Grid ref={grid} columns={cols} rows={rows} initialSelected={1} band={isHeader} />
    </div>
  );
}
