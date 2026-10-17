import { useEffect, useMemo, useRef, useState } from "react";
import { commandInputRef } from "../components/CommandLine";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { downloadCsv } from "../csv";
import { fmtAge, fmtBig, fmtChg, fmtPct, fmtPrice, fmtTime, sign } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api, type Quote } from "../net/api";
import { subscribe } from "../net/socket";
import { getLive, onTicks, SRC_LABEL } from "../state/ticks";
import { navigate, replaceView } from "../state/workspace";
import type { FunctionProps } from "./registry";

export const DEFAULT_LIST = ["SPY", "QQQ", "DIA", "^NSEI", "^BSESN", "AAPL", "MSFT", "RELIANCE.NS", "INFY.NS", "BTC-USD", "EURUSD=X", "GC=F", "CL=F"];

interface Row {
  input: string;
  symbol: string;
  q?: Quote;
  stale?: boolean;
  fetchedAt: number;
  ageAtFetch: number;
  error?: string;
}

const SORTS = ["INPUT", "SYMBOL", "%CHG", "VOLUME"] as const;
type Sort = (typeof SORTS)[number];

const price = (r: Row) => getLive(r.symbol)?.price ?? r.q?.price ?? null;
const pct = (r: Row) => getLive(r.symbol)?.pct ?? r.q?.change_pct ?? null;
const chg = (r: Row) => getLive(r.symbol)?.change ?? r.q?.change ?? null;
const vol = (r: Row) => getLive(r.symbol)?.volume ?? r.q?.volume ?? null;
const dirColor = (v: number | null): CellColor => (sign(v) > 0 ? "up" : sign(v) < 0 ? "down" : "fg");

function srcText(r: Row): string {
  const l = getLive(r.symbol);
  if (l) return SRC_LABEL[l.src] ?? l.src;
  if (r.error) return "";
  const age = r.ageAtFetch + (Date.now() - r.fetchedAt) / 1000;
  return r.stale ? `STALE ${fmtAge(age)}` : (r.q?.source ?? "").toUpperCase();
}

function srcColor(r: Row): CellColor {
  const l = getLive(r.symbol);
  if (l) return l.src === "s" ? "warn" : "up";
  return r.stale ? "warn" : "dim";
}

const COLUMNS: Column<Row>[] = [
  { title: "SECURITY", width: 11, text: (r) => r.symbol, color: (r) => (r.error ? "err" : "acc") },
  { title: "SRC", width: 9, text: srcText, color: srcColor },
  { title: "NAME", width: 14, text: (r) => r.error ?? r.q?.name ?? "", color: (r) => (r.error ? "err" : "dim") },
  {
    title: "LAST", width: 12, align: "right", text: (r) => fmtPrice(price(r)),
    color: (r) => { const l = getLive(r.symbol); return l ? dirColor(l.dir) : "fg"; },
    flash: (r, f) => { const l = getLive(r.symbol); return l && l.frame === f && l.dir ? (l.dir > 0 ? "up" : "down") : null; },
  },
  { title: "CHG", width: 10, align: "right", text: (r) => fmtChg(chg(r)), color: (r) => dirColor(chg(r)) },
  { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(pct(r)), color: (r) => dirColor(pct(r)) },
  { title: "VOLUME", width: 9, align: "right", text: (r) => fmtBig(vol(r)) },
  { title: "HIGH", width: 11, align: "right", text: (r) => fmtPrice(getLive(r.symbol)?.high ?? r.q?.high) },
  { title: "LOW", width: 11, align: "right", text: (r) => fmtPrice(getLive(r.symbol)?.low ?? r.q?.low) },
  { title: "TIME", width: 8, align: "right", text: (r) => fmtTime(getLive(r.symbol)?.t ?? (r.q?.market_time ? r.q.market_time * 1000 : null)) },
  { title: "CCY", width: 4, text: (r) => r.q?.currency ?? "", color: () => "dim" },
];

export default function Q({ panelId, args, security }: FunctionProps) {
  const inputs = useMemo(() => {
    const list = args.map((a) => a.toUpperCase()).filter(Boolean);
    if (list.length) return list;
    return security ? [security.symbol] : DEFAULT_LIST;
  }, [args, security]);
  const usingDefault = !args.length && !security;

  const [rows, setRows] = useState<Row[]>(() => inputs.map((s) => ({ input: s, symbol: s, fetchedAt: Date.now(), ageAtFetch: 0 })));
  const [sort, setSort] = useState<Sort>("INPUT");
  const sortRef = useRef<Sort>("INPUT");
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const grid = useRef<GridHandle>(null);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;

  // Snapshot (REST), then live ticks (WS) take over.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .quotes(inputs)
      .then(({ results }) => {
        if (!alive) return;
        const now = Date.now();
        setRows(
          inputs.map((input) => {
            const r = results[input];
            if (!r) return { input, symbol: input, fetchedAt: now, ageAtFetch: 0, error: "NO DATA FOR SYMBOL" };
            if ("error" in r) return { input, symbol: r.symbol ?? input, fetchedAt: now, ageAtFetch: 0, error: r.error };
            return { input, symbol: r.data.symbol, q: r.data, stale: r.stale, fetchedAt: now, ageAtFetch: r.age_s };
          }),
        );
      })
      .catch((e: ApiError) => {
        if (alive) setRows(inputs.map((s) => ({ input: s, symbol: s, fetchedAt: Date.now(), ageAtFetch: 0, error: e.message })));
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [inputs, reload]);

  const symbolsKey = rows.filter((r) => !r.error).map((r) => r.symbol).join(",");
  useEffect(() => (symbolsKey ? subscribe(symbolsKey.split(",")) : undefined), [symbolsKey]);

  // Repaint only rows whose symbol ticked this frame.
  useEffect(() => {
    const index = new Map<string, number[]>();
    rows.forEach((r, i) => index.set(r.symbol, [...(index.get(r.symbol) ?? []), i]));
    const off = onTicks((changed, frame) => {
      const hit: number[] = [];
      for (const s of changed) {
        const idx = index.get(s);
        if (idx) hit.push(...idx);
      }
      if (hit.length) grid.current?.redrawRows(hit, frame);
    });
    const ageTimer = setInterval(() => grid.current?.redraw(), 5000); // AGE/STALE text keeps counting
    return () => {
      off();
      clearInterval(ageTimer);
    };
  }, [rows]);

  // Panel keys.
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = rowsRef.current;
        const sel = g?.selected() ?? 0;
        switch (e.key) {
          case "j":
          case "ArrowDown":
            g?.move(1);
            return true;
          case "k":
          case "ArrowUp":
            g?.move(-1);
            return true;
          case "g":
          case "Home":
            g?.moveTo(0);
            return true;
          case "G":
          case "End":
            g?.moveTo(cur.length - 1);
            return true;
          case "PageDown":
            g?.page(1);
            return true;
          case "PageUp":
            g?.page(-1);
            return true;
          case "Enter": {
            const r = cur[sel];
            if (r) navigate(panelId, { fn: "DES", security: { symbol: r.symbol }, args: [] });
            return true;
          }
          case "d": {
            const r = cur[sel];
            if (!r) return true;
            const next = cur.filter((_, i) => i !== sel).map((x) => x.input);
            replaceView(panelId, (v) => ({ ...v, args: next.length ? next : ["SPY"] }));
            return true;
          }
          case "a": {
            const el = commandInputRef.current;
            if (el) {
              el.focus();
              el.value = `${panelId}: Q ${cur.map((x) => x.input).join(" ")} `;
            }
            return true;
          }
          case "s": {
            const next = SORTS[(SORTS.indexOf(sortRef.current) + 1) % SORTS.length];
            const by = (r: Row) => (next === "%CHG" ? -(pct(r) ?? -Infinity) : next === "VOLUME" ? -(vol(r) ?? -Infinity) : 0);
            // Sorted once, on request: live re-sorting on every tick would make rows jump under the cursor.
            const sorted =
              next === "INPUT"
                ? inputs.map((i) => cur.find((r) => r.input === i)).filter((r): r is Row => !!r)
                : next === "SYMBOL"
                  ? [...cur].sort((x, y) => x.symbol.localeCompare(y.symbol))
                  : [...cur].sort((x, y) => by(x) - by(y));
            sortRef.current = next;
            setSort(next);
            setRows(sorted);
            return true;
          }
          case "e":
            downloadCsv(`Q_${cur.map((r) => r.symbol).join("_").slice(0, 60)}`, COLUMNS.map((c) => c.title), cur.map((r) => COLUMNS.map((c) => c.text(r))));
            return true;
          case "F5":
            setReload((n) => n + 1);
            return true;
        }
        return false;
      }),
    [panelId, inputs],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">QUOTE MONITOR</span> {rows.length} SECURITIES{usingDefault && " (DEFAULT LIST)"} · SORT {sort}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim"> · J/K MOVE · ENTER DES · A ADD · D DEL · S SORT · E CSV · F5 REFRESH</span>
      </div>
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
