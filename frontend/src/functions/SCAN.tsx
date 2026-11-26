/**
 * SCAN (Phase 27): check a universe of symbols against a BT rule on each one's newest daily bar.
 * `SCAN SPX RSI14<30 AND CLOSE>SMA200`. The server downloads the bars (paced for Yahoo: a cold 500-name scan takes about a
 * minute, shown as progress) and evaluates the rule in a job. Matched rows come first with the value of every term the rule
 * uses. Keys: J/K move, Enter opens GP of the selected symbol in a new panel (with the rule's averages / RSI / ATR drawn),
 * A shows all rows or matches only, E saves a CSV. `SCAN SAVE ... DAILY=HH:MM` sends the matches every weekday (DELIVERY).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { execute } from "../command/execute";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { PanelNote } from "../components/PanelNote";
import { fmtNum, fmtPrice } from "../format";
import { navKey } from "../keys/gridNav";
import { registerPanelKeys } from "../keys/panelKeys";
import { errText } from "../net/errText";
import { scanApi } from "../net/scanApi";
import type { ScanResult, ScanRow, ScanSaved } from "../net/types";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gpStudies, parseScanArgs, SCAN_USAGE, UNIVERSES } from "./scanArgs";
import { gridCsv, useCsvExport } from "./tableExport";
import { useTaskPoll } from "./useTaskPoll";

function columns(res: ScanResult): Column<ScanRow>[] {
  return [
    { title: "SYMBOL", width: 12, text: (r) => r.symbol, color: (r) => (r.matched ? "acc" : "fg") },
    { title: "MATCH", width: 6, text: (r) => (r.matched ? "YES" : r.valid ? "NO" : "—"), color: (r) => (r.matched ? "up" : "dim") },
    { title: "BAR", width: 11, text: (r) => r.date ?? "—", color: () => "dim" },
    { title: "CLOSE", width: 11, align: "right", text: (r) => fmtPrice(r.close) },
    ...res.terms.filter((t) => t !== "CLOSE").map((t): Column<ScanRow> => ({ title: t, width: Math.max(8, t.length + 1), align: "right", text: (r) => fmtNum(r.values[t], 2), color: () => "val" })),
    { title: "NOTE", width: 40, text: (r) => r.note, color: () => "err" },
  ];
}

const SAVED_COLS: Column<ScanSaved>[] = [
  { title: "NAME", width: 14, text: (s) => s.name, color: () => "acc" },
  { title: "UNIVERSE", width: 14, text: (s) => s.universe },
  { title: "DAILY", width: 7, text: (s) => s.daily ?? "—", color: (s) => (s.daily ? "up" : "dim") },
  { title: "RULE", width: 60, text: (s) => s.rule },
];

export default function SCAN({ panelId, args }: FunctionProps) {
  const parsed = useMemo(() => parseScanArgs(args), [args]);
  const [saved, setSaved] = useState<ScanSaved[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [all, setAll] = useState(true);
  const grid = useRef<GridHandle>(null);
  const isScan = parsed.ok && parsed.act === "scan";
  const { task, error } = useTaskPoll<ScanResult>(
    isScan ? () => scanApi.start({ universe: parsed.universe, rule: parsed.rule }) : null, scanApi.task, parsed);

  useEffect(() => {
    if (!parsed.ok || parsed.act === "scan") return;
    const list = () => scanApi.saved().then((r) => setSaved(r.saved), (e) => setMsg(`ERR: ${errText(e)}`));
    if (parsed.act === "saved") void list();
    else if (parsed.act === "save")
      scanApi.save(parsed.name, { universe: parsed.universe, rule: parsed.rule, daily: parsed.daily })
        .then((s) => { setMsg(`SAVED ${s.name}${s.daily ? `: SENT EVERY WEEKDAY AT ${s.daily} (THIS COMPUTER'S TIME) THROUGH DELIVERY` : ""}`); void list(); },
          (e) => setMsg(`ERR: ${errText(e)}`));
    else if (parsed.act === "del") scanApi.del(parsed.name).then(() => { setMsg(`DELETED ${parsed.name}`); void list(); }, (e) => setMsg(`ERR: ${errText(e)}`));
    else if (parsed.act === "run") {
      setMsg(`RUNNING ${parsed.name} AND SENDING IT…`);
      scanApi.runSaved(parsed.name).then((r) => setMsg(r.sent ? `SENT ${parsed.name}: ${r.matched} MATCHES` : `ERR: ${r.error}`), (e) => setMsg(`ERR: ${errText(e)}`));
    }
  }, [parsed]);

  const res = task?.state === "done" ? task.result : null;
  const rows = useMemo(() => (res ? (all ? res.rows : res.rows.filter((r) => r.matched)) : []), [res, all]);
  const cols = useMemo(() => (res ? columns(res) : []), [res]);
  const latest = useLatest({ rows, res, saved });
  useCsvExport(panelId, () => (latest.current.res ? gridCsv("SCAN", columns(latest.current.res), latest.current.rows) : null));
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const { rows: rs, res: r } = latest.current;
        if (!r) return false;
        if (navKey(e, grid.current, rs.length)) return true;
        if (e.key === "a") return setAll((v) => !v), true;
        if (e.key === "Enter") {
          const row = rs[grid.current?.selected() ?? 0];
          if (row) execute(`${row.symbol} GP 1Y ${gpStudies(r.terms).join(" ")}`.trim(), { newPanel: true });
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  return (
    <div className="fn scan">
      <div className="line">
        <span className="acc">SCAN </span>
        {isScan ? `${parsed.universe} · ${parsed.rule}` : "SAVED SCANS"}
        {task?.source ? <span className="dim"> · {task.source}</span> : null}
      </div>
      {!parsed.ok && <PanelNote kind="error" hint={`UNIVERSE: ${UNIVERSES}`}>{parsed.error}</PanelNote>}
      {error && <PanelNote kind="error" hint={SCAN_USAGE}>ERR: {error}</PanelNote>}
      {task?.state === "error" && <PanelNote kind="error">ERR: {task.error}</PanelNote>}
      {task && (task.state === "fetching" || task.state === "running") && (
        <div className="line">
          <span className="acc">{task.state === "fetching" ? "DOWNLOADING BARS " : "CHECKING THE RULE "}</span>
          {task.done} OF {task.total} <span className="dim">· YAHOO LIMITS SPEED: A COLD 500-NAME SCAN TAKES ABOUT A MINUTE</span>
        </div>
      )}
      {msg && <div className="dim">{msg}</div>}
      {res && (
        <>
          <div className="line">
            <span className="up">{res.matched} MATCH</span> OF {res.checked} CHECKED
            {res.failed ? <span className="warn"> · PARTIAL: {res.failed} WITHOUT DATA</span> : null}
            <span className="dim"> · {res.labels.prices} · {res.labels.bars}{res.labels.fixtures ? ` · ${res.labels.fixtures}` : ""} · NEWEST BAR (TODAY'S MAY STILL BE FORMING)</span>
          </div>
          <div className="dim legend">J/K MOVE · ENTER GP · A {all ? "MATCHES ONLY" : "ALL ROWS"} · E CSV</div>
          <Grid ref={grid} columns={cols} rows={rows} />
        </>
      )}
      {parsed.ok && parsed.act !== "scan" && saved && (
        saved.length ? <Grid columns={SAVED_COLS} rows={saved} /> : <PanelNote kind="empty" hint="SCAN SAVE OVERSOLD SPX RSI14<30 DAILY=22:15">NO SAVED SCANS</PanelNote>
      )}
    </div>
  );
}
