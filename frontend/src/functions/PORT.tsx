/**
 * Portfolios: `PORT` lists them, `PORT NAME` shows one as a live P&L grid (Phase 8). Stored in SQLite.
 * Mixed currencies are converted to the base with live FX and labelled (see portfolioMath.ts).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  deletePortfolio, importInto, portfolioList, portfolioRequest, portfolioVersion, refreshPortfolios, removePositions,
  restorePortfolio, takeRequest,
} from "../command/portfolios";
import { prefillCommand } from "../components/CommandLine";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { fmtChg, fmtPct, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { api8, type ApiError, type Position } from "../net/api";
import { subscribe } from "../net/socket";
import { LAYOUT_NAME_RE } from "../state/layoutState";
import { useStore } from "../state/store";
import { getLive, onTicks } from "../state/ticks";
import { navigate } from "../state/workspace";
import { exportPositions, importPositions, type ImportResult } from "./portfolioCsv";
import { calcRow, fxSymbol, totals, weight, type RowCalc, type Totals } from "./portfolioMath";
import { chg, dirColor, lastColor, lastFlash, navKey, price, srcColor, srcText, useLatest, useLiveRows, useQuotes, type QRow } from "./quoteRows";
import type { FunctionProps } from "./registry";

const when = (t: number) => {
  const d = new Date(t * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};

const fmtQty = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 4 });
const fmtMoney = (v: number | null | undefined) => fmtPrice(v);

export default function PORT({ panelId, args }: FunctionProps) {
  const name = args[0]?.toUpperCase();
  if (!name) return <PortfolioIndex panelId={panelId} />;
  if (!LAYOUT_NAME_RE.test(name)) return <div className="err">PORTFOLIO NAME: 1-32 OF A-Z 0-9 _ . -</div>;
  return <PortfolioView key={name} panelId={panelId} name={name} />;
}

interface PRow {
  pos: Position;
  q?: QRow;
}

const SORTS = ["INPUT", "SYMBOL", "MKT VAL", "DAY P&L", "UNRL P&L", "UNRL %"] as const;
type Sort = (typeof SORTS)[number];

function downloadText(filename: string, text: string): void {
  // BOM so spreadsheet apps read UTF-8; the importer strips it.
  const url = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

type ImportState = { stage: "paste" } | { stage: "preview"; source: string; result: ImportResult } | null;

function PortfolioView({ panelId, name }: { panelId: number; name: string }) {
  const version = useStore(portfolioVersion, (v) => v);
  const request = useStore(portfolioRequest, (r) => r);
  const [pf, setPf] = useState<{ base: string; positions: Position[] } | null>(null);
  const [missing, setMissing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [sort, setSort] = useState<Sort>("INPUT");
  const [confirm, setConfirm] = useState<string | null>(null);
  const [imp, setImp] = useState<ImportState>(null);
  const [, setFrameTick] = useState(0);
  const undo = useRef<Position[] | null>(null);
  const grid = useRef<GridHandle>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let alive = true;
    api8
      .portfolio(name)
      .then((p) => {
        if (!alive) return;
        setPf({ base: p.base, positions: p.positions });
        setMissing(false);
        setErr(null);
      })
      .catch((e: ApiError) => {
        if (!alive) return;
        if (e.status === 404) {
          setPf({ base: "USD", positions: [] });
          setMissing(true);
        } else setErr(e.message);
      });
    return () => {
      alive = false;
    };
  }, [name, version, reload]);

  const base = pf?.base ?? "USD";
  const positions = useMemo(() => pf?.positions ?? [], [pf]);
  const symKey = positions.map((p) => p.symbol).join(",");
  const inputs = useMemo(() => (symKey ? symKey.split(",") : []), [symKey]);
  const { rows: quoteRows, loading } = useQuotes(inputs, reload);

  // FX legs for every non-base currency (from the quote, else the position's own currency).
  const fxKey = useMemo(() => {
    const ccys = new Set<string>();
    positions.forEach((p) => {
      const c = quoteRows.find((r) => r.input === p.symbol)?.q?.currency ?? p.currency;
      const fx = c ? fxSymbol(c, base) : null;
      if (fx) ccys.add(fx);
    });
    return [...ccys].sort().join(",");
  }, [positions, quoteRows, base]);
  const fxInputs = useMemo(() => (fxKey ? fxKey.split(",") : []), [fxKey]);
  const { rows: fxRows } = useQuotes(fxInputs, reload);
  useEffect(() => (fxKey ? subscribe(fxKey.split(",")) : undefined), [fxKey]);

  const rate = (fx: string) => getLive(fx)?.price ?? fxRows.find((r) => r.input === fx)?.q?.price ?? null;
  const calcOf = (r: PRow): RowCalc =>
    calcRow(
      { symbol: r.pos.symbol, qty: r.pos.qty, cost: r.pos.cost, posCurrency: r.pos.currency, quoteCurrency: r.q?.q?.currency ?? null, last: r.q ? price(r.q) : null, change: r.q ? chg(r.q) : null },
      base,
      rate,
    );

  const baseRows = useMemo<PRow[]>(() => {
    const bySym = new Map(quoteRows.map((q) => [q.input, q]));
    return positions.map((pos) => ({ pos, q: bySym.get(pos.symbol) }));
  }, [positions, quoteRows]);
  const [order, setOrder] = useState<string[] | null>(null);
  const rows = useMemo(() => {
    if (!order) return baseRows;
    const at = new Map(order.map((s, i) => [s, i]));
    return [...baseRows].sort((a, b) => (at.get(a.pos.symbol) ?? 1e9) - (at.get(b.pos.symbol) ?? 1e9));
  }, [baseRows, order]);

  const tot = useRef<Totals>(totals([], base));
  tot.current = totals(rows.map((r) => ({ symbol: r.pos.symbol, calc: calcOf(r) })), base);
  const latest = useLatest({ rows, sort, positions, base, confirm, imp, calcOf });

  useLiveRows(rows, grid, (r: PRow) => (r.q?.error ? undefined : r.pos.symbol));

  // Totals and weights move with every tick of any leg: refresh them at most 4 times a second.
  useEffect(() => {
    const watched = new Set([...inputs, ...fxInputs]);
    let pending = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const off = onTicks((changed) => {
      if (pending) return;
      for (const s of changed) {
        if (!watched.has(s)) continue;
        pending = true;
        timer = setTimeout(() => {
          pending = false;
          setFrameTick((n) => n + 1);
          grid.current?.redraw();
        }, 250);
        return;
      }
    });
    return () => {
      off();
      clearTimeout(timer); // a pending refresh must not fire on an unmounted or re-keyed panel
    };
  }, [inputs, fxInputs]);

  const columns = useMemo<Column<PRow>[]>(() => {
    const c = (r: PRow) => latest.current.calcOf(r);
    const pnlColor = (v: number | null): CellColor => dirColor(v);
    return [
      { title: "SECURITY", width: 11, text: (r) => r.pos.symbol, color: (r) => (r.q?.error ? "err" : "acc") },
      { title: "SRC", width: 9, text: (r) => (r.q ? srcText(r.q) : ""), color: (r) => (r.q ? srcColor(r.q) : "dim") },
      { title: "QTY", width: 10, align: "right", text: (r) => fmtQty(r.pos.qty), color: (r) => (r.pos.qty < 0 ? "down" : "fg") },
      { title: "AVG COST", width: 11, align: "right", text: (r) => fmtPrice(r.pos.cost) },
      { title: "LAST", width: 11, align: "right", text: (r) => fmtPrice(r.q ? price(r.q) : null), color: (r) => (r.q ? lastColor(r.q) : "fg"), flash: (r, f) => (r.q ? lastFlash(r.q, f) : null) },
      { title: "DAY CHG", width: 9, align: "right", text: (r) => fmtChg(r.q ? chg(r.q) : null), color: (r) => dirColor(r.q ? chg(r.q) : null) },
      { title: "DAY P&L", width: 12, align: "right", text: (r) => fmtChg(c(r).day), color: (r) => pnlColor(c(r).day) },
      { title: "MKT VAL", width: 13, align: "right", text: (r) => fmtMoney(c(r).mv) },
      { title: "UNRL P&L", width: 13, align: "right", text: (r) => fmtChg(c(r).unrl), color: (r) => pnlColor(c(r).unrl) },
      { title: "UNRL %", width: 8, align: "right", text: (r) => fmtPct(c(r).unrlPct), color: (r) => pnlColor(c(r).unrlPct) },
      { title: "WGHT", width: 7, align: "right", text: (r) => fmtPct(weight(c(r), tot.current)).replace("+", "") },
      {
        title: "CCY", width: 11,
        text: (r) => {
          const k = c(r);
          if (k.mismatch) return `${r.pos.currency}≠${k.ccy}`;
          if (!k.ccy) return "?";
          if (k.converted) return k.mvBase == null && k.mv != null ? `${k.ccy} NO FX` : `${k.ccy}→${latest.current.base}`;
          return k.ccy;
        },
        color: (r) => {
          const k = c(r);
          return k.mismatch || (k.mvBase == null && k.mv != null) ? "warn" : k.converted ? "acc" : "dim";
        },
      },
      { title: "NOTES", width: 24, text: (r) => r.q?.error ?? r.pos.notes ?? "", color: (r) => (r.q?.error ? "err" : "dim") },
    ];
  }, [latest]);

  const doExport = () => {
    const { positions: list, base: b } = latest.current;
    const text = exportPositions(list, (s) => {
      const q = latest.current.rows.find((r) => r.pos.symbol === s)?.q;
      return q ? price(q) : null;
    });
    downloadText(`PORT_${name}_${b}.csv`, text);
    return list.length;
  };

  const preview = (source: string, text: string) => setImp({ stage: "preview", source, result: importPositions(text) });

  // EXPORT / IMPORT typed on the command line.
  useEffect(() => {
    if (!pf) return;
    const act = takeRequest(name);
    if (act === "export") doExport();
    if (act === "import") setImp({ stage: "paste" });
  }, [request, pf, name]);

  useEffect(() => {
    if (imp?.stage === "paste") textarea.current?.focus();
  }, [imp]);

  const apply = (mode: "merge" | "replace") => {
    const imp = latest.current.imp; // the key handler is registered once: never read the render's own `imp`
    if (imp?.stage !== "preview" || !imp.result.rows.length) return;
    const list = imp.result.rows.map(({ symbol, qty, cost, currency, notes }) => ({ symbol, qty, cost, currency, notes }));
    setImp(null);
    void importInto(name, list, mode);
  };

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, sort: curSort, positions: list, confirm: c, imp: im, calcOf: calc } = latest.current;
        if (im?.stage === "preview") {
          if (e.key === "Enter") apply("merge");
          else if (e.key === "r") apply("replace");
          else if (e.key === "Escape") setImp(null);
          return true; // the preview is modal
        }
        if (c && e.key !== "d" && e.key !== "Delete") setConfirm(null);
        if (navKey(e, g, cur.length)) return true;
        const r = cur[g?.selected() ?? -1];
        switch (e.key) {
          case "Enter":
            if (r) navigate(panelId, { fn: "GP", security: { symbol: r.pos.symbol }, args: [] });
            return true;
          case "a":
            prefillCommand(`PORT ${name} ADD `);
            return true;
          case "b":
            prefillCommand(`PORT ${name} BASE `);
            return true;
          case "d":
          case "Delete":
            if (!r) return true;
            if (c !== r.pos.symbol) {
              setConfirm(r.pos.symbol);
              return true;
            }
            setConfirm(null);
            undo.current = list;
            setPf((p) => (p ? { ...p, positions: p.positions.filter((x) => x.symbol !== r.pos.symbol) } : p));
            void removePositions(name, [r.pos.symbol], `REMOVED ${r.pos.symbol} FROM ${name}. U UNDOES.`);
            return true;
          case "u":
            if (undo.current) {
              const before = undo.current;
              undo.current = null;
              void restorePortfolio(name, before);
            }
            return true;
          case "s": {
            const next = SORTS[(SORTS.indexOf(curSort) + 1) % SORTS.length];
            setSort(next);
            if (next === "INPUT") setOrder(null);
            else {
              const key = (x: PRow): number | string => {
                const k = calc(x);
                const v = next === "MKT VAL" ? k.mvBase : next === "DAY P&L" ? k.dayBase : next === "UNRL P&L" ? k.unrlBase : next === "UNRL %" ? k.unrlPct : null;
                return next === "SYMBOL" ? x.pos.symbol : -(v ?? -Infinity);
              };
              const sorted = [...cur].sort((x, y) => {
                const a = key(x);
                const b = key(y);
                return typeof a === "string" ? a.localeCompare(b as string) : a - (b as number);
              });
              setOrder(sorted.map((x) => x.pos.symbol));
            }
            return true;
          }
          case "e":
            doExport();
            return true;
          case "i":
            fileInput.current?.click(); // inside the keypress: the browser allows the file dialog
            return true;
          case "v":
            setImp({ stage: "paste" });
            return true;
          case "F5":
            setReload((n) => n + 1);
            return true;
          case "Escape":
            return c !== null;
        }
        return false;
      }),
    // apply/doExport read everything through `latest`
    [panelId, name, latest],
  );

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (f.size > 2_000_000) {
      setErr("CSV OVER 2 MB");
      return;
    }
    void f.text().then((t) => preview(f.name, t));
  };

  const onPasteKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    e.stopPropagation(); // typing here must not reach panel keys or type-to-command
    if (e.key === "Escape") {
      e.preventDefault();
      setImp(null);
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      preview("PASTED TEXT", e.currentTarget.value);
    } else if (e.key.toLowerCase() === "o" && e.ctrlKey) {
      e.preventDefault();
      fileInput.current?.click();
    }
  };

  const t = tot.current;
  const tc = (v: number | null) => (v == null ? "" : v > 0 ? "up" : v < 0 ? "down" : "");
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">PORTFOLIO {name}</span> {rows.length} POSITIONS · BASE {base} · SORT {sort}
        {(loading || pf === null) && <span className="dim"> · LOADING…</span>}
        {err && <span className="err"> · STALE: {err}</span>}
        {confirm && <span className="err"> · REMOVE {confirm}? PRESS D AGAIN</span>}
        <span className="dim"> · J/K MOVE · ENTER GP · A ADD · D REMOVE · U UNDO · S SORT · E EXPORT · I IMPORT FILE · V PASTE CSV · B BASE · F5</span>
      </div>
      {missing && <div className="dim">NO PORTFOLIO {name}. PORT {name} ADD AAPL 10 150 CREATES IT (OR I / V TO IMPORT A CSV).</div>}
      {!missing && pf && positions.length === 0 && <div className="dim">EMPTY. A ADDS A POSITION (PORT {name} ADD SYM QTY [COST]).</div>}
      <Grid ref={grid} columns={columns} rows={rows} />
      <div className="summary" data-testid="port-summary">
        TOTAL {base} MKT VAL <span className="acc">{fmtMoney(t.mv)}</span> · DAY{" "}
        <span className={tc(t.day)}>{fmtChg(t.day)} ({fmtPct(t.dayPct)})</span> · UNRL{" "}
        <span className={tc(t.unrl)}>{fmtChg(t.unrl)} ({fmtPct(t.unrlPct)})</span> · COST {fmtMoney(t.cost)}
        {t.converted.length > 0 && <span className="acc"> · CONVERTED AT LIVE FX: {t.converted.map((c) => `${c}${base}=X`).join(" ")}</span>}
        {t.unconverted.map((u) => (
          <span key={u.ccy} className="warn">
            {" "}· NOT IN TOTAL: {u.ccy} {fmtMoney(u.mv)} ({u.count}){u.ccy.includes("MISMATCH") ? "" : " NO FX RATE YET"}
          </span>
        ))}
        {t.noPrice.length > 0 && <span className="dim"> · NO PRICE: {t.noPrice.join(" ")}</span>}
      </div>
      <input ref={fileInput} type="file" accept=".csv,text/csv,text/plain" style={{ display: "none" }} onChange={onFile} data-testid="port-file" />
      {imp && <ImportBox state={imp} textarea={textarea} onPasteKey={onPasteKey} name={name} />}
    </div>
  );
}

function ImportBox({ state, textarea, onPasteKey, name }: {
  state: NonNullable<ImportState>;
  textarea: React.RefObject<HTMLTextAreaElement | null>;
  onPasteKey: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  name: string;
}) {
  if (state.stage === "paste") {
    return (
      <div className="import">
        <div className="acc">IMPORT CSV INTO {name}: PASTE BELOW · CTRL+ENTER PREVIEW · CTRL+O CHOOSE FILE · ESC CANCEL</div>
        <textarea ref={textarea} spellCheck={false} aria-label="CSV text" placeholder="symbol,quantity,avg_cost,currency,notes" onKeyDown={onPasteKey} />
      </div>
    );
  }
  const { result: r, source } = state;
  const m = Object.entries(r.mapping).map(([f, h]) => `${f.toUpperCase()}←${h}`).join(" ");
  return (
    <div className="import" data-testid="port-preview">
      <div className="acc">
        PREVIEW {source}: {r.rows.length} ROWS OK · <span className={r.errors.length ? "err" : "dim"}>{r.errors.length} ERRORS (NOT IMPORTED)</span>
        {r.rows.length ? " · ENTER MERGE (UPSERT) · R REPLACE ALL · ESC CANCEL" : " · NOTHING TO IMPORT · ESC CANCEL"}
      </div>
      {m && <div className="dim">COLUMNS: {m}</div>}
      {r.warnings.map((w) => (
        <div key={w} className="warn">{w}</div>
      ))}
      {r.errors.map((e) => (
        <div key={e.line} className="err">
          LINE {e.line}: {e.reason} · {e.text.slice(0, 80)}
        </div>
      ))}
      <table className="t">
        <thead>
          <tr>
            <th>LINE</th>
            <th>SYMBOL</th>
            <th className="n">QTY</th>
            <th className="n">AVG COST</th>
            <th>CCY</th>
            <th>NOTES</th>
          </tr>
        </thead>
        <tbody>
          {r.rows.slice(0, 200).map((x) => (
            <tr key={x.line}>
              <td className="dim">{x.line}</td>
              <td>{x.symbol}</td>
              <td className="n">{fmtQty(x.qty)}</td>
              <td className="n">{fmtPrice(x.cost)}</td>
              <td>{x.currency ?? ""}</td>
              <td className="dim">{x.notes ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {r.rows.length > 200 && <div className="dim">… AND {r.rows.length - 200} MORE ROWS (ALL WILL BE IMPORTED)</div>}
    </div>
  );
}

/** `PORT` with no name: saved portfolios, keyboard driven (same keys as the WL index). */
function PortfolioIndex({ panelId }: { panelId: number }) {
  const list = useStore(portfolioList, (l) => l);
  const [sel, setSel] = useState(0);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const state = useLatest({ list, sel, confirm });

  const refresh = () =>
    refreshPortfolios()
      .then(() => setErr(null))
      .catch((e: ApiError) => setErr(e.message));

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { list: l, sel: i, confirm: c } = state.current;
        const n = l?.length ?? 0;
        const name = l?.[Math.min(i, n - 1)]?.name;
        if (c && e.key !== "Delete" && e.key !== "x") setConfirm(null);
        switch (e.key) {
          case "j":
          case "ArrowDown":
            setSel(Math.min(n - 1, i + 1));
            return true;
          case "k":
          case "ArrowUp":
            setSel(Math.max(0, i - 1));
            return true;
          case "Enter":
            if (name) navigate(panelId, { fn: "PORT", args: [name] });
            return true;
          case "Delete":
          case "x":
            if (!name) return true;
            if (c === name) {
              setConfirm(null);
              void deletePortfolio(name);
            } else setConfirm(name);
            return true;
          case "n":
            prefillCommand("PORT ");
            return true;
          case "F5":
            void refresh();
            return true;
          case "Escape":
            return c !== null;
        }
        return false;
      }),
    [panelId, state],
  );

  if (!list) return <div className={err ? "err" : "dim"}>{err ? `PORTFOLIOS UNAVAILABLE: ${err}` : "LOADING…"}</div>;
  const i = Math.min(sel, list.length - 1);
  return (
    <div>
      <h2>
        PORTFOLIOS {err && <span className="err">STALE: {err}</span>}
      </h2>
      {list.length === 0 ? (
        <div className="dim">NO PORTFOLIOS. PORT NAME ADD AAPL 10 150 CREATES ONE.</div>
      ) : (
        <table className="t">
          <colgroup>
            <col style={{ width: 20 }} />
            <col style={{ width: 260 }} />
            <col style={{ width: 60 }} />
            <col style={{ width: 90 }} />
            <col style={{ width: 140 }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th />
              <th>NAME</th>
              <th>BASE</th>
              <th className="n">POSITIONS</th>
              <th>UPDATED</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.map((p, k) => (
              <tr key={p.name} className={k === i ? "on" : ""} aria-selected={k === i}>
                <td className="acc">{k === i ? ">" : ""}</td>
                <td>{p.name}</td>
                <td className="dim">{p.base}</td>
                <td className="n">{p.count}</td>
                <td className="dim">{when(p.updated_at)}</td>
                <td>{confirm === p.name && <span className="err">DELETE? PRESS DEL AGAIN</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="dim">J K / ↑ ↓ SELECT · ENTER OPEN · DEL DELETE · N NEW · F5 REFRESH · PORT NAME ADD SYM QTY [COST]</div>
    </div>
  );
}
