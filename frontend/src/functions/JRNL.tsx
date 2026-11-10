/**
 * JRNL: your own trade journal. Import a broker file (Zerodha tradebook, IBKR Flex, Alpaca, or any CSV you map), then read it as FIFO
 * round trips, statistics, behaviour findings (heuristics over YOUR history, not advice) and a Shadow Account (the same entries with one
 * fixed exit rule, replayed through the backtester as a job). Nothing is converted between currencies; one currency is shown at a time.
 * Keys: 1-5 view · C currency · R reload · S run the shadow account · I import · X twice clears the journal · J/K move.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { errText } from "../net/errText";
import { journalApi } from "../net/journalApi";
import { adoptJob, useJob } from "../net/jobs";
import { useLatest } from "../state/useLatest";
import {
  BROKERS, VIEWS, fmtDur, fmtMoney, fmtPct, fmtRatio, importBody, mappingToText, nextOf, parseArgs,
  type JrnlAnalysis, type JrnlFinding, type JrnlPreview, type JrnlTrip, type JrnlView,
} from "./journalModel";
import type { FunctionProps } from "./registry";

const sign = (x: number): "up" | "down" | "fg" => (x > 0 ? "up" : x < 0 ? "down" : "fg");
const TRIP_COLS: Column<JrnlTrip>[] = [
  { title: "SYMBOL", width: 14, text: (r) => r.symbol, color: () => "acc" },
  { title: "SIDE", width: 6, text: (r) => r.side.toUpperCase() },
  { title: "QTY", width: 10, align: "right", text: (r) => String(r.qty) },
  { title: "ENTRY", width: 17, text: (r) => r.entry_time.replace("T", " ").slice(0, 16), color: () => "dim" },
  { title: "EXIT", width: 17, text: (r) => r.exit_time.replace("T", " ").slice(0, 16), color: () => "dim" },
  { title: "IN", width: 11, align: "right", text: (r) => fmtMoney(r.entry_price, 2) },
  { title: "OUT", width: 11, align: "right", text: (r) => fmtMoney(r.exit_price, 2) },
  { title: "HELD", width: 7, align: "right", text: (r) => fmtDur(r.hold_s) },
  { title: "FEES", width: 9, align: "right", text: (r) => fmtMoney(r.fees) },
  { title: "P&L", width: 12, align: "right", text: (r) => fmtMoney(r.pnl), color: (r) => sign(r.pnl) },
  { title: "P&L %", width: 8, align: "right", text: (r) => fmtPct(r.pnl_pct, 2), color: (r) => sign(r.pnl) },
];

export default function JRNL({ panelId, args }: FunctionProps) {
  const parsed = useMemo(() => parseArgs(args), [args]);
  const [view, setView] = useState<JrnlView>(parsed.view);
  const [currency, setCurrency] = useState<string | undefined>(parsed.currency);
  const [data, setData] = useState<JrnlAnalysis | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [shadowId, setShadowId] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);
  const latest = useLatest({ view, data, currency, confirm });

  useEffect(() => {
    setView(parsed.view);
    setCurrency(parsed.currency);
  }, [parsed]);

  const load = useCallback((ccy?: string) => {
    journalApi
      .analysis(ccy)
      .then((a) => {
        setData(a);
        setMsg(null);
        if (a.empty) setView((v) => (v === "IMPORT" ? v : "IMPORT"));
      })
      .catch((e) => setMsg(`ERR: ${errText(e)}`));
  }, []);
  useEffect(() => load(currency), [currency, load]);

  const startShadow = useCallback(() => {
    setMsg("STARTING SHADOW ACCOUNT…");
    journalApi
      .shadow({ currency: latest.current.data?.currency ?? undefined })
      .then((j) => {
        adoptJob(j);
        setShadowId(j.id);
        setMsg(null);
      })
      .catch((e) => setMsg(`ERR: ${errText(e)}`));
  }, [latest]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.metaKey || e.altKey) return false;
        const { view: v, data: d, confirm: c } = latest.current;
        if (e.key >= "1" && e.key <= "5") {
          setView(VIEWS[Number(e.key) - 1]);
          return true;
        }
        const k = e.key.toLowerCase();
        if (k === "i") return setView("IMPORT"), true;
        if (k === "r") return load(latest.current.currency), true;
        if (k === "c" && d && d.currencies.length > 1) {
          setCurrency(nextOf(d.currencies.map((x) => x.currency), d.currency ?? d.currencies[0].currency));
          return true;
        }
        if (k === "s" && v === "SHADOW") return startShadow(), true;
        if (k === "x") {
          if (c) {
            setConfirm(false);
            journalApi
              .clear()
              .then((r) => {
                setMsg(`CLEARED ${r.deleted} FILLS`);
                load(undefined);
              })
              .catch((er) => setMsg(`ERR: ${errText(er)}`));
          } else setConfirm(true);
          return true;
        }
        if (v === "TRIPS" && d?.round_trips && navKey(e, grid.current, d.round_trips.length)) return true;
        return false;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- everything is read through `latest`
    [panelId, latest],
  );

  const tabs = (
    <div className="line">
      <span className="acc">JRNL</span>{" "}
      {VIEWS.map((v, i) => (
        <span key={v} className={v === view ? "acc" : "dim"}>
          {i + 1} {v}{" "}
        </span>
      ))}
      <span className="dim">
        · {data && !data.empty ? `${data.currency} (${data.currencies.map((c) => `${c.currency} ${c.round_trips}`).join(", ")})` : ""} · C CURRENCY · R RELOAD
        · X TWICE CLEARS
      </span>
      {confirm && <span className="err"> · CLEAR THE WHOLE JOURNAL? PRESS X AGAIN</span>}
    </div>
  );

  return (
    <div className="fn">
      {tabs}
      {parsed.bad && <div className="err">{parsed.bad} · USAGE: JRNL [TRIPS|STATS|FINDINGS|SHADOW|IMPORT] [CCY]</div>}
      {msg && <div className={msg.startsWith("ERR") ? "err" : "dim"}>{msg}</div>}
      {view === "IMPORT" && <ImportView panelId={panelId} onDone={() => load(undefined)} />}
      {view !== "IMPORT" && !data && !msg && <div className="dim">LOADING…</div>}
      {view !== "IMPORT" && data?.empty && <div className="dim">NO TRADES IMPORTED YET: PRESS I</div>}
      {view !== "IMPORT" && data && !data.empty && (
        <>
          {data.labels && <div className="dim">{data.labels.note} {data.labels.times}</div>}
          {view === "TRIPS" && <Trips data={data} grid={grid} />}
          {view === "STATS" && <Stats data={data} />}
          {view === "FINDINGS" && <Findings list={data.diagnostics ?? []} ccy={data.currency ?? ""} />}
          {view === "SHADOW" && <Shadow id={shadowId} onRun={startShadow} />}
        </>
      )}
    </div>
  );
}

function Trips({ data, grid }: { data: JrnlAnalysis; grid: React.RefObject<GridHandle | null> }) {
  const rows = data.round_trips ?? [];
  return (
    <>
      <div className="line dim">
        {data.round_trips_total ?? rows.length} ROUND TRIPS (FIFO, NEWEST LAST) · J/K MOVE
        {(data.round_trips_total ?? 0) > rows.length ? ` · SHOWING THE LAST ${rows.length}` : ""}
      </div>
      {rows.length ? <Grid ref={grid} columns={TRIP_COLS} rows={rows} initialSelected={rows.length - 1} /> : <div className="dim">NO CLOSED ROUND TRIPS YET</div>}
      {(data.open_positions ?? []).length > 0 && (
        <div className="line">
          <span className="acc">STILL OPEN</span> <span className="dim">(NOT MARKED TO ANY PRICE)</span>{" "}
          {(data.open_positions ?? []).map((p) => `${p.symbol} ${p.side.toUpperCase()} ${p.qty} @ ${fmtMoney(p.avg_price)} SINCE ${p.since.slice(0, 10)}`).join(" · ")}
        </div>
      )}
    </>
  );
}

function Stats({ data }: { data: JrnlAnalysis }) {
  const s = data.stats;
  if (!s || !s.n) return <div className="dim">NO CLOSED ROUND TRIPS IN {data.currency} YET</div>;
  const ccy = data.currency ?? "";
  const rows: [string, string][] = [
    ["ROUND TRIPS", `${s.n} (${s.wins} WON, ${s.losses} LOST, ${s.flat} FLAT)`],
    ["WIN RATE", fmtPct(s.win_rate)],
    ["AVG WIN / AVG LOSS", `${fmtMoney(s.avg_win)} / ${fmtMoney(s.avg_loss)} ${ccy}`],
    ["PAYOFF RATIO", fmtRatio(s.payoff)],
    ["EXPECTANCY / TRIP", `${fmtMoney(s.expectancy)} ${ccy}`],
    ["PROFIT FACTOR", fmtRatio(s.profit_factor)],
    ["NET P&L (GROSS, FEES)", `${fmtMoney(s.total_pnl)} (${fmtMoney(s.gross_pnl)}, ${fmtMoney(s.fees)}) ${ccy}`],
    ["BEST / WORST", `${fmtMoney(s.best)} / ${fmtMoney(s.worst)} ${ccy}`],
    ["HELD: AVG / MEDIAN", `${fmtDur(s.avg_hold_s)} / ${fmtDur(s.median_hold_s)}`],
    ["HELD: WINNERS / LOSERS", `${fmtDur(s.avg_hold_win_s)} / ${fmtDur(s.avg_hold_loss_s)}`],
    ["LONGEST STREAKS", `${s.max_consec_wins} WINS · ${s.max_consec_losses} LOSSES`],
    ["MAX DRAWDOWN (REALISED)", `${fmtMoney(s.max_drawdown)} ${ccy}${s.max_drawdown_end ? ` ENDING ${s.max_drawdown_end.slice(0, 10)}` : ""}`],
    ["PERIOD", `${s.first?.slice(0, 10)} TO ${s.last?.slice(0, 10)}`],
  ];
  const grp = (title: string, g: { key: string; n: number; pnl: number; win_rate: number }[] | undefined) =>
    g && g.length > 0 && (
      <div>
        <div className="line acc">{title}</div>
        {g.slice(0, 12).map((x) => (
          <div key={x.key} className="line">
            {x.key.padEnd(12)} {String(x.n).padStart(4)} TRIPS {fmtPct(x.win_rate, 0).padStart(5)} WON <span className={sign(x.pnl) === "up" ? "up" : sign(x.pnl) === "down" ? "down" : ""}>{fmtMoney(x.pnl).padStart(14)}</span>
          </div>
        ))}
      </div>
    );
  return (
    <div>
      {rows.map(([k, v]) => (
        <div key={k} className="line">
          <span className="dim">{k.padEnd(26)}</span> {v}
        </div>
      ))}
      {grp("BY SYMBOL (WORST FIRST)", s.by_symbol)}
      {grp("BY WEEKDAY OF ENTRY", s.by_weekday)}
      {grp("BY HOUR OF ENTRY (FILE'S OWN CLOCK)", s.by_hour)}
    </div>
  );
}

const SEV: Record<JrnlFinding["severity"], string> = { none: "dim", watch: "warn", high: "err" };

function Findings({ list, ccy }: { list: JrnlFinding[]; ccy: string }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div>
      <div className="line warn">HEURISTICS OVER YOUR OWN HISTORY IN {ccy}: PATTERNS TO LOOK AT, NOT ADVICE AND NOT A FORECAST. EACH RULE IS PRINTED.</div>
      {list.map((f) => (
        <div key={f.id} data-testid={`finding-${f.id}`}>
          <div className="line">
            <button type="button" onClick={() => setOpen(open === f.id ? null : f.id)} aria-expanded={open === f.id}>
              <span className={SEV[f.severity]}>{f.status.toUpperCase()}</span> <span className="acc">{f.title}</span>
            </button>
          </div>
          <div className="line">{f.plain}</div>
          <div className="dim">RULE: {f.rule}</div>
          {open === f.id && f.trips.length > 0 && (
            <pre className="desc">
              {f.trips.slice(0, 20).map((t) => `${t.symbol.padEnd(12)} ${t.side.padEnd(5)} ${t.entry_time.slice(0, 16).replace("T", " ")} → ${t.exit_time.slice(0, 16).replace("T", " ")}  ${fmtMoney(t.pnl).padStart(12)}`).join("\n")}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

interface ShadowSide { equity: [number, number][]; metrics: Record<string, number | null> }
interface ShadowResult {
  labels: { headline: string; notes: string[]; prices: string; rule: string; fixtures?: boolean; sources: { symbol: string; name: string | null; stale: boolean }[] };
  currency: string; replayed: number; skipped_trips: number; skipped_reasons: Record<string, number>; skipped_symbols: { symbol: string; why: string }[];
  you: ShadowSide; alt: ShadowSide; journal_pnl: { total: number; currency: string }; symbols: string[];
}
const METRICS: [string, string, (x: number | null | undefined) => string][] = [
  ["total_return", "TOTAL RETURN", (x) => fmtPct(x)], ["annual_return", "ANNUAL RETURN", (x) => fmtPct(x)], ["max_drawdown", "MAX DRAWDOWN", (x) => fmtPct(x)],
  ["sharpe", "SHARPE", fmtRatio], ["trade_count", "TRADES", (x) => (x == null ? "-" : String(x))], ["win_rate", "WIN RATE", (x) => fmtPct(x)],
  ["profit_loss_ratio", "PROFIT/LOSS RATIO", fmtRatio],
];

function Shadow({ id, onRun }: { id: string | null; onRun: () => void }) {
  const job = useJob(id);
  const res = job?.state === "done" ? (job.result as ShadowResult | undefined) : undefined;
  return (
    <div>
      <div className="line">
        <span className="acc">SHADOW ACCOUNT</span>{" "}
        <span className="dim">
          YOUR REAL ENTRIES, ONE FIXED EXIT RULE (HOLD N DAYS, OR YOUR MEDIAN LOSS AS STOP AND TWICE THAT AS TARGET), BOTH REPLAYED THROUGH THE BACKTESTER ON DAILY BARS. S RUNS IT.
        </span>
      </div>
      {!id && <div className="dim">PRESS S TO RUN (A JOB; SEE JOBS)</div>}
      {job && (job.state === "queued" || job.state === "running") && (
        <div className="dim">
          RUNNING {Math.round((job.progress ?? 0) * 100)}% {job.msg}
        </div>
      )}
      {job && (job.state === "error" || job.state === "cancelled") && (
        <div className="err">
          {job.state.toUpperCase()}: {job.error ?? ""} · S TRIES AGAIN
        </div>
      )}
      {res && (
        <div data-testid="shadow-result">
          <div className="line warn">{res.labels.headline} · {res.labels.rule} · PRICES {res.labels.prices}{res.labels.fixtures ? " · FIXTURE DATA" : ""}</div>
          <div className="line">
            <span className="dim">{"METRIC".padEnd(20)}</span> {"YOUR EXITS".padStart(12)} {"RULE EXITS".padStart(12)}
          </div>
          {METRICS.map(([k, title, f]) => (
            <div key={k} className="line">
              <span className="dim">{title.padEnd(20)}</span> {f(res.you.metrics[k]).padStart(12)} {f(res.alt.metrics[k]).padStart(12)}
            </div>
          ))}
          <div className="line dim">
            REPLAYED {res.replayed} TRIPS ON {res.symbols.join(", ")} · YOUR REAL NET P&L ON THESE: {fmtMoney(res.journal_pnl.total)} {res.journal_pnl.currency}
            {res.skipped_trips > 0 ? ` · SKIPPED ${res.skipped_trips}: ${Object.entries(res.skipped_reasons).map(([k, v]) => `${k} x${v}`).join(", ")}` : ""}
          </div>
          {res.skipped_symbols.length > 0 && <div className="warn">NO BARS FOR: {res.skipped_symbols.map((s) => `${s.symbol} (${s.why})`).join("; ")}</div>}
          {res.labels.sources.some((s) => s.stale) && <div className="warn">SOME BARS ARE STALE: SEE THE SOURCE LINE BELOW</div>}
          <div className="dim">BARS: {res.labels.sources.map((s) => `${s.symbol} ${s.name ?? "?"}`).join(" · ")}</div>
          {res.labels.notes.map((n) => (
            <div key={n} className="dim">· {n}</div>
          ))}
        </div>
      )}
      {!job && id && <div className="dim">WAITING FOR THE JOB…</div>}
      <button type="button" onClick={onRun}>
        [S] RUN AGAIN
      </button>
    </div>
  );
}

function ImportView({ panelId, onDone }: { panelId: number; onDone: () => void }) {
  const [form, setForm] = useState({ text: "", name: "", broker: "auto", mapping: "", dateOrder: "", currency: "USD" });
  const [preview, setPreview] = useState<JrnlPreview | null>(null);
  const [out, setOut] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const latest = useLatest(form);
  useEffect(() => {
    box.current?.focus();
    const t = setTimeout(() => box.current?.focus(), 80);
    return () => clearTimeout(t);
  }, []);
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.metaKey || e.altKey) return false;
        const k = e.key.toLowerCase();
        if (k === "b") return setForm((f) => ({ ...f, broker: nextOf(BROKERS, f.broker as (typeof BROKERS)[number]) })), true;
        if (k === "d") return setForm((f) => ({ ...f, dateOrder: f.dateOrder === "" ? "DMY" : f.dateOrder === "DMY" ? "MDY" : "" })), true;
        return false;
      }),
    [panelId],
  );

  // Look at the file once it is pasted: the detected broker and (for a generic file) a guessed column mapping.
  useEffect(() => {
    if (!form.text.trim()) return void setPreview(null);
    const t = setTimeout(() => {
      journalApi
        .preview(form.text)
        .then((p) => {
          setPreview(p);
          setErr(null);
          setForm((f) => (f.mapping || !Object.keys(p.mapping).length ? f : { ...f, mapping: mappingToText(p.mapping), broker: p.broker ? f.broker : f.broker === "auto" ? "generic" : f.broker }));
        })
        .catch((e) => {
          setPreview(null);
          setErr(`${errText(e)}`);
        });
    }, 300);
    return () => clearTimeout(t);
  }, [form.text]);

  const store = () => {
    const f = latest.current;
    if (!f.text.trim()) return;
    setOut("IMPORTING…");
    setErr(null);
    journalApi
      .importFile(importBody(f))
      .then((r) => {
        setOut(`IMPORTED ${r.added} NEW FILLS (${r.duplicates} ALREADY THERE, ${r.ignored} ROWS NOT TRADES) FROM ${r.broker.toUpperCase()} · ${r.first.slice(0, 10)} TO ${r.last.slice(0, 10)}`);
        setForm((x) => ({ ...x, text: "" }));
        onDone();
      })
      .catch((e) => {
        setOut(null);
        setErr(`${errText(e)}${e && typeof e === "object" && "detail" in e && e.detail ? `\n${String(e.detail)}` : ""}`);
      });
  };
  const onKey = (e: React.KeyboardEvent<HTMLElement>) => {
    if (!((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) e.stopPropagation();
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      store();
    } else if (e.key.toLowerCase() === "o" && e.ctrlKey) {
      e.preventDefault();
      file.current?.click();
    } else if (e.key === "Escape") {
      e.preventDefault();
      (e.currentTarget as HTMLElement).blur();
    }
  };
  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (f) void f.text().then((text) => setForm((x) => ({ ...x, text, name: f.name })));
  };
  const generic = form.broker === "generic";
  return (
    <div>
      <div className="line">
        <span className="acc">IMPORT</span>{" "}
        <span className="dim">
          PASTE A ZERODHA TRADEBOOK, IBKR FLEX TRADES CSV, ALPACA ACTIVITIES CSV OR YOUR OWN CSV · CTRL+ENTER IMPORTS · CTRL+O CHOOSE FILE · ESC LEAVES THE BOX · B BROKER · D DATE ORDER ·
          RE-IMPORTING THE SAME FILE ADDS NOTHING
        </span>
      </div>
      <div className="line">
        BROKER <span className="acc">{form.broker.toUpperCase()}</span> · SLASH DATES <span className="acc">{form.dateOrder || "NOT SET"}</span> · CURRENCY{" "}
        <input aria-label="Default currency" size={4} maxLength={3} value={form.currency} onKeyDown={onKey} onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value }))} />
        <span className="dim"> (USED WHEN THE FILE HAS NONE; NOTHING IS CONVERTED)</span>
      </div>
      <div className="import">
        <textarea ref={box} spellCheck={false} aria-label="Broker file text" value={form.text} onChange={(e) => setForm((f) => ({ ...f, text: e.target.value }))} onKeyDown={onKey} placeholder="paste the file here" />
      </div>
      <input ref={file} type="file" accept=".csv,text/csv,text/plain" style={{ display: "none" }} onChange={onFile} data-testid="jrnl-file" />
      {preview && (
        <div data-testid="jrnl-preview" className="line">
          {preview.rows} ROWS · DETECTED <span className="acc">{preview.broker ? preview.broker.toUpperCase() : "NOT RECOGNISED: SET BROKER TO GENERIC (B) AND MAP COLUMNS"}</span> · COLUMNS: {preview.columns.join(", ")}
        </div>
      )}
      {generic && (
        <div className="line">
          MAP <span className="dim">(field=Column: time symbol side qty price fee currency order_id)</span>{" "}
          <input aria-label="Column mapping" size={60} value={form.mapping} onKeyDown={onKey} onChange={(e) => setForm((f) => ({ ...f, mapping: e.target.value }))} />
        </div>
      )}
      {err && <pre className="err">ERR: {err}</pre>}
      {out && <div className="line">{out}</div>}
    </div>
  );
}
