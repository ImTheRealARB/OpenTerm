/**
 * Currency cross matrix. Row = 1 unit of that currency, column = its price in the column currency.
 * Every cell is triangulated through USD from Yahoo's USDxxx=X legs and recomputed when a leg ticks.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { fmtRate } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { subscribe } from "../net/socket";
import { getLive, onTicks } from "../state/ticks";
import { navigate } from "../state/workspace";
import { crossPair, crossRate, parseCurrencies, usdLeg } from "./boards";
import { navKey, useLatest, useQuotes, type QRow } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

interface Row {
  ccy: string;
}

export default function FXC({ panelId, args }: FunctionProps) {
  const parsed = useMemo(() => parseCurrencies(args), [args]);
  const list = parsed.ok ? parsed.list : [];
  const legs = useMemo(() => list.map(usdLeg).filter((s): s is string => !!s), [list]);
  const [reload, setReload] = useState(0);
  const { rows: quotes, loading } = useQuotes(legs, reload);
  const grid = useRef<GridHandle>(null);

  // Leg lookups by currency; read at draw time so ticks need no React render.
  const legRows = useMemo(() => new Map<string, QRow>(quotes.map((q) => [q.input.slice(3, 6), q])), [quotes]);
  const rate = (ccy: string, prev = false): number | null => {
    if (ccy === "USD") return 1;
    const r = legRows.get(ccy);
    if (!r || r.error) return null;
    return prev ? (r.q?.prev_close ?? null) : (getLive(r.symbol)?.price ?? r.q?.price ?? null);
  };
  const legState = useLatest(rate);

  // New row objects per snapshot so the grid repaints and re-describes the selected row.
  const rows = useMemo<Row[]>(() => list.map((ccy) => ({ ccy })), [list, quotes]);
  const cols = useMemo<Column<Row>[]>(() => {
    const now: Record<string, number | null> = {};
    const cell = (base: string, quote: string, prev: boolean) => {
      for (const c of [base, quote]) now[c] = legState.current(c, prev);
      return crossRate(now, base, quote);
    };
    const color = (base: string, quote: string): CellColor => {
      if (base === quote) return "dim";
      const a = cell(base, quote, false);
      const b = cell(base, quote, true);
      return a == null || b == null || a === b ? "fg" : a > b ? "up" : "down";
    };
    return [
      { title: "1 UNIT", width: 6, text: (r) => r.ccy, color: () => "acc" },
      ...list.map<Column<Row>>((q) => ({
        title: q,
        width: 10,
        align: "right",
        text: (r) => (r.ccy === q ? "—" : fmtRate(cell(r.ccy, q, false))),
        color: (r) => color(r.ccy, q),
      })),
    ];
  }, [list, legState]);
  const latest = useLatest(rows);
  useCsvExport(panelId, () => gridCsv(`FXC_${list.join("_")}`, cols, rows));

  const legKey = quotes.filter((q) => !q.error).map((q) => q.symbol).join(",");
  useEffect(() => (legKey ? subscribe(legKey.split(",")) : undefined), [legKey]);
  useEffect(() => {
    const mine = new Set(legKey.split(","));
    return onTicks((changed) => {
      for (const s of changed) if (mine.has(s)) return grid.current?.redraw(); // every cell may use this leg
    });
  }, [legKey]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "Enter": {
            const r = cur[g?.selected() ?? -1];
            if (r) navigate(panelId, { fn: "GP", security: { symbol: crossPair(r.ccy, "USD") }, args: [] });
            return true;
          }
          case "F5":
            setReload((n) => n + 1);
            return true;
        }
        return false;
      }),
    [panelId, list, cols, latest],
  );

  if (!parsed.ok) return <div className="err">{parsed.error}. USAGE: FXC [CCY CCY ...], E.G. FXC USD EUR INR</div>;
  const missing = quotes.filter((q) => q.error).map((q) => q.input.slice(3, 6));
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">CROSS RATES</span> {list.length} CURRENCIES · ROW = 1 UNIT, PRICED IN EACH COLUMN · TRIANGULATED VIA USD
        {loading && <span className="dim"> · LOADING…</span>}
        {missing.length > 0 && <span className="err"> · NO RATE: {missing.join(" ")}</span>}
        <span className="dim legend"> · J/K MOVE · ENTER CHART VS USD · E CSV · F5 REFRESH</span>
      </div>
      <Grid ref={grid} columns={cols} rows={rows} />
    </div>
  );
}
