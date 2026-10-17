/** A fixed, sectioned live board (WEI, FX, CMDTY): REST snapshot, then streamed ticks. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtChg, fmtPct, fmtPrice, fmtRate, fmtTime } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { getLive } from "../state/ticks";
import { navigate } from "../state/workspace";
import type { BoardDef } from "./boards";
import { chg, dirColor, lastColor, lastFlash, navKey, pct, price, quoteTime, srcColor, srcText, useLatest, useLiveRows, useQuotes, type QRow } from "./quoteRows";
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

function columns(def: BoardDef): Column<BRow>[] {
  const num = def.rates ? fmtRate : fmtPrice;
  const signed = (v: number | null) => (v == null ? fmtChg(v) : (v > 0 ? "+" : "") + num(v));
  const cols: Column<BRow>[] = [
    { title: "NAME", width: 20, text: (r) => r.section ?? r.label, color: (r) => (r.section ? "fg" : "acc") },
    { title: "SECURITY", width: 11, text: (r) => r.symbol, color: (r) => (r.error ? "err" : "dim") },
    { title: "SRC", width: 9, text: srcText, color: srcColor },
    { title: "LAST", width: 12, align: "right", text: (r) => num(price(r)), color: lastColor, flash: lastFlash },
    { title: "CHG", width: 10, align: "right", text: (r) => signed(chg(r)), color: (r) => dirColor(chg(r)) },
    { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(pct(r)), color: (r) => dirColor(pct(r)) },
    { title: "HIGH", width: 11, align: "right", text: (r) => num(getLive(r.symbol)?.high ?? r.q?.high) },
    { title: "LOW", width: 11, align: "right", text: (r) => num(getLive(r.symbol)?.low ?? r.q?.low) },
    { title: "TIME", width: 8, align: "right", text: (r) => fmtTime(quoteTime(r)) },
  ];
  if (def.sections.some((s) => s.items.some((i) => i.unit))) cols.push({ title: "UNIT", width: 9, text: (r) => r.unit ?? "", color: () => "dim" });
  // Header rows show only their title; errors replace the numbers on their own row.
  return cols.map((c, i) => ({
    ...c,
    text: (r) => (r.section ? (i === 0 ? r.section : "") : r.error && i === 2 ? r.error : c.text(r)),
    color: (r) => (r.error && i === 2 ? "err" : (c.color?.(r) ?? "fg")),
  }));
}

export function Board({ panelId, def }: FunctionProps & { def: BoardDef }) {
  const inputs = useMemo(() => def.sections.flatMap((s) => s.items.map((i) => i.symbol)), [def]);
  const cols = useMemo(() => columns(def), [def]);
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
        <span className="acc">{def.title}</span> {inputs.length} {def.noun}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim"> · J/K MOVE · ENTER CHART · E CSV · F5 REFRESH</span>
      </div>
      <Grid ref={grid} columns={cols} rows={rows} initialSelected={1} />
    </div>
  );
}
