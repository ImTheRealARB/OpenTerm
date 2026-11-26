/**
 * BT LIVE (Phase 26): paper forward tests. A saved strategy runs on NEW bars with play money in OpenTerm's own book (no broker,
 * no ORD, no order anywhere). The list shows each test's forward result next to a backtest of the same period on today's
 * data; a bar where the two decided differently is DIVERGED (a warning sign: look-ahead, repainting or revised data).
 * Keys: J/K move, Enter details (Esc back), R check now (new bars), S stop the selected test. The server also checks every
 * 15 minutes while it runs; decisions made late (several bars at once) are marked CATCH-UP.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { LIVE_USAGE, parseLiveArgs } from "../bt/liveArgs";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { PanelNote } from "../components/PanelNote";
import { fmtAge, fmtNum, fmtPct, fmtPrice } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { btApi } from "../net/btApi";
import { errText } from "../net/errText";
import { adoptJob, useJob } from "../net/jobs";
import type { BtFwdFull, BtFwdSummary } from "../net/types";
import { useLatest } from "../state/useLatest";

const DIR = ["SHORT", "FLAT", "LONG"];
const dirText = (d: number) => DIR[d + 1] ?? "?";
const day = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);
const sign = (v: number | null | undefined): CellColor => (v == null || v === 0 ? "fg" : v > 0 ? "up" : "down");
const pct = (v: number | null | undefined) => (v == null ? "—" : fmtPct(v * 100));

const LIST_COLS: Column<BtFwdSummary>[] = [
  { title: "ID", width: 9, text: (s) => s.id, color: () => "dim" },
  { title: "SYMBOL", width: 10, text: (s) => s.symbol, color: () => "acc" },
  { title: "STRATEGY", width: 14, text: (s) => `@${s.strategy}` },
  { title: "BARS", width: 5, text: (s) => s.interval, color: () => "dim" },
  { title: "STATUS", width: 8, text: (s) => s.status.toUpperCase(), color: (s) => (s.status === "active" ? "up" : "dim") },
  { title: "NOW", width: 6, text: (s) => dirText(s.pos) },
  { title: "DECIDED", width: 8, align: "right", text: (s) => String(s.decisions) },
  { title: "CATCH-UP", width: 9, align: "right", text: (s) => String(s.late), color: (s) => (s.late ? "warn" : "dim") },
  { title: "FILLS", width: 6, align: "right", text: (s) => String(s.fills) },
  { title: "FORWARD", width: 9, align: "right", text: (s) => pct(s.live_return), color: (s) => sign(s.live_return) },
  { title: "BACKTEST", width: 9, align: "right", text: (s) => pct(s.bt_return), color: (s) => sign(s.bt_return) },
  { title: "DIVERGED", width: 9, align: "right", text: (s) => String(s.n_diverged), color: (s) => (s.n_diverged ? "err" : "dim") },
  { title: "CHECKED", width: 10, text: (s) => (s.checked ? `${fmtAge(Date.now() / 1000 - s.checked)} AGO` : "NEVER"), color: () => "dim" },
  { title: "ERROR", width: 40, text: (s) => s.error ?? "", color: () => "err" },
];

interface DecisionRow {
  t: number;
  live: number;
  late: boolean;
  today: number | null;
}
const DECISION_COLS: Column<DecisionRow>[] = [
  { title: "BAR", width: 11, text: (r) => day(r.t) },
  { title: "FORWARD", width: 8, text: (r) => dirText(r.live), color: (r) => sign(r.live) },
  { title: "WHEN", width: 9, text: (r) => (r.late ? "CATCH-UP" : "ON TIME"), color: (r) => (r.late ? "warn" : "dim") },
  { title: "TODAY'S BACKTEST", width: 17, text: (r) => (r.today == null ? "SAME" : `${dirText(r.today)} (DIVERGED)`), color: (r) => (r.today == null ? "dim" : "err") },
];

export default function BtLive({ panelId, args }: { panelId: number; args: string[] }) {
  const parsed = useMemo(() => parseLiveArgs(args), [args]);
  const [tests, setTests] = useState<BtFwdSummary[] | null>(null);
  const [open, setOpen] = useState<BtFwdFull | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const grid = useRef<GridHandle>(null);

  const reload = (openId?: string) => {
    btApi
      .fwdList()
      .then((r) => setTests(r.tests))
      .catch((e) => setError(errText(e)));
    if (openId) btApi.fwdGet(openId).then(setOpen).catch((e) => setError(errText(e)));
  };

  // The command: start / stop / delete, then show the list (or the new test).
  useEffect(() => {
    setError(null);
    if (!parsed.ok) return setError(parsed.error);
    if (parsed.act === "list") return reload();
    if (parsed.act === "start") {
      setMsg(`STARTING A FORWARD TEST OF @${parsed.strategy} ON ${parsed.symbol}…`);
      btApi
        .fwdCreate({ symbol: parsed.symbol, strategy: parsed.strategy, interval: parsed.interval, ...(parsed.cash ? { cash: parsed.cash } : {}) })
        .then((r) => {
          setMsg(`STARTED ${r.test.id}: PLAY MONEY, FILLS AT THE NEXT BAR'S OPEN · FIRST CHECK RUNNING…`);
          setJobId(adoptJob(r.job).id);
          reload(r.test.id);
        })
        .catch((e) => setError(errText(e)));
      return;
    }
    const call = parsed.act === "stop" ? btApi.fwdStop(parsed.id) : btApi.fwdDelete(parsed.id);
    call.then(() => { setMsg(`${parsed.act === "stop" ? "STOPPED" : "DELETED"} ${parsed.id}`); reload(); }).catch((e) => setError(errText(e)));
     
  }, [parsed]);

  // A check finished: the server already applied it (job on-done hook), so re-read.
  useEffect(() => {
    if (!job) return;
    if (job.state === "done") {
      setMsg("CHECKED");
      reload(latest.current.open?.id);
    } else if (job.state === "error") setMsg(`CHECK FAILED: ${job.error ?? job.msg ?? "ERROR"}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reacts to the job record only
  }, [job?.state]);

  const decisions = useMemo<DecisionRow[]>(() => {
    if (!open) return [];
    const other = new Map((open.backtest?.diverged ?? []).map(([t, , today]) => [t, today]));
    return [...open.decisions].reverse().map(([t, live, late]) => ({ t, live, late, today: other.get(t) ?? null }));
  }, [open]);

  const latest = useLatest({ tests, open, decisions });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { tests: ts, open: o, decisions: ds } = latest.current;
        if (o) {
          if (e.key === "Escape") return setOpen(null), true;
          if (navKey(e, grid.current, ds.length)) return true;
        } else if (ts && navKey(e, grid.current, ts.length)) return true;
        const sel = o ? o.summary : ts?.[grid.current?.selected() ?? 0];
        if (!sel) return false;
        if (e.key === "Enter" && !o) {
          btApi.fwdGet(sel.id).then(setOpen).catch((err) => setError(errText(err)));
          return true;
        }
        if (e.key === "r") {
          setMsg(`CHECKING ${sel.id} FOR NEW BARS…`);
          btApi.fwdStep(sel.id).then((j) => setJobId(adoptJob(j).id)).catch((err) => setMsg(`ERR: ${errText(err)}`));
          return true;
        }
        if (e.key === "s") {
          btApi.fwdStop(sel.id).then(() => { setMsg(`STOPPED ${sel.id}`); reload(o?.id); }).catch((err) => setMsg(`ERR: ${errText(err)}`));
          return true;
        }
        return false;
      }),
     
    [panelId, latest],
  );

  const bt = open?.backtest;
  return (
    <div className="fn bt bt-live">
      <div className="line">
        <span className="acc">BT LIVE </span>
        PAPER FORWARD TESTS · PLAY MONEY IN OPENTERM'S OWN BOOK (NO BROKER, NO ORDERS) · RAW PRICES, NO FEES OR SLIPPAGE
      </div>
      {error && <PanelNote kind="error" hint={LIVE_USAGE}>ERR: {error}</PanelNote>}
      {msg && <div className="dim">{msg}</div>}
      {!open && tests && !tests.length && (
        <PanelNote kind="empty" hint="Save a strategy first (BT SAVE NAME SMA20>SMA50), then BT LIVE AAPL @NAME.">NO FORWARD TESTS YET</PanelNote>
      )}
      {!open && tests && tests.length > 0 && (
        <>
          <div className="dim legend">J/K MOVE · ENTER DETAILS · R CHECK NOW · S STOP · CHECKED EVERY 15 MINUTES WHILE OPENTERM RUNS</div>
          <Grid ref={grid} columns={LIST_COLS} rows={tests} />
        </>
      )}
      {open && (
        <>
          <div className="line">
            <span className="acc">{open.summary.symbol} @{open.summary.strategy}</span> {open.summary.interval} · STARTED {day(open.summary.started)} · {open.summary.status.toUpperCase()} · NOW {dirText(open.summary.pos)}
            <span className="dim"> · ESC BACK · R CHECK NOW · S STOP</span>
          </div>
          {bt ? (
            <div className="line">
              FORWARD <span className={sign(bt.live_return)}>{pct(bt.live_return)}</span> · TODAY'S BACKTEST OF THE SAME PERIOD{" "}
              <span className={sign(bt.return)}>{pct(bt.return)}</span> · {open.fills.length} VS {bt.fills} FILLS · PRICE {fmtPrice(bt.price)}
              {bt.n_diverged ? <span className="err"> · {bt.n_diverged} DIVERGED BARS: A WARNING SIGN (LOOK-AHEAD, REPAINTING OR REVISED DATA)</span> : <span className="up"> · NO DIVERGED BARS</span>}
            </div>
          ) : (
            <div className="dim">NOT CHECKED YET</div>
          )}
          {open.fills.length > 0 && (
            <div className="dim">
              FILLS: {open.fills.slice(-6).map(([t, side, qty, px]) => `${day(t)} ${side} ${fmtNum(qty, 2)} @ ${fmtPrice(px)}`).join(" · ")}
            </div>
          )}
          {decisions.length ? <Grid ref={grid} columns={DECISION_COLS} rows={decisions} /> : <PanelNote kind="empty" hint="Decisions appear once a bar that started after the test began is complete.">NO DECISIONS YET</PanelNote>}
        </>
      )}
    </div>
  );
}
