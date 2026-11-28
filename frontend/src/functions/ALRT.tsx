/** Alerts: every saved price / percent alert with its live price and state (Phase 8). The backend engine fires them (Phase 20); command/alerts.ts shows the result app-wide. */
import { useEffect, useMemo, useRef, useState } from "react";
import { alerts, alertsError, alertText, failureIsRecorded, newsAlertsError, clearAlerts, deleteAlert, deleteNewsAlert, engineState, newsAlerts, notifyState, rearmAlert, rearmNewsAlert, refreshAlerts, refreshEngine, refreshNewsAlerts, refreshNotifyState, type NotifyState } from "../command/alerts";
import { viaText } from "../command/alertArgs";
import { prefillCommand } from "../components/CommandLine";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtPct, fmtPrice, fmtTime } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import type { Alert, NewsAlert, SmartAlert } from "../net/types";
import type { ScriptAlert } from "../net/scriptsApi";
import { deleteScriptAlert, refreshScriptAlerts } from "../script/liveAlertSync";
import { RUNS_WHILE_OPEN, scriptAlertRuns, scriptAlerts, scriptAlertsError, scriptAlertText, type ScriptAlertRun } from "../script/liveAlertState";
import { smartAlertsApi } from "../net/smartAlertsApi";
import { errText } from "../net/errText";
import { useStore } from "../state/store";
import { openExternal } from "../safeUrl";
import { navigate } from "../state/workspace";
import { plainAlert } from "./alertPlain";
import { engineView } from "./alertEngineText";
import { requestAsk } from "../gui/askBus";
import { PanelNote } from "../components/PanelNote";
import { settingsStore } from "../settings/runtime";
import { dirColor, lastColor, lastFlash, pct, price, useLiveRows, useQuotes, type QRow } from "./quoteRows";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

/**
 * A price / percent alert (`a`), a news keyword alert (`n`, shown with the id N<id>) or a live script alert (`s`, id SC<id>).
 * A script alert is checked by THIS browser while OpenTerm is open (`script/liveAlerts.ts`), so its state is the tab's own `run`.
 */
interface ARow {
  a: Alert | null;
  n: NewsAlert | null;
  s: ScriptAlert | null;
  run?: ScriptAlertRun;
  q?: QRow;
}
const rid = (r: ARow) => (r.a ? String(r.a.id) : r.n ? `N${r.n.id}` : `SC${r.s!.id}`);
const rsym = (r: ARow) => r.a?.symbol ?? (r.n ? (r.n.symbol ?? "MARKET") : r.s!.symbol);
/** Price / news: the server's status. Script: `error` when its run stopped, else `running` (a script alert fires many times, it never "triggers" once). */
const rstatus = (r: ARow) => (r.s ? (r.run?.state === "error" ? "error" : r.run?.state === "loading" || !r.run ? "loading" : "running") : (r.a ?? r.n!).status);
const rtriggered = (r: ARow) => (r.s ? r.run?.firedAt : (r.a ?? r.n!).triggered_at);
const rcreated = (r: ARow) => (r.s ? r.s.created_at : (r.a ?? r.n!).created_at);
const statusColor = (r: ARow) => (rstatus(r) === "error" ? "err" : rstatus(r) === "triggered" || rstatus(r) === "loading" ? "warn" : "up");
/** What the long last column says: a script alert's reach and last firing or error; a news alert's headline. */
const rdetail = (r: ARow) =>
  r.s ? [RUNS_WHILE_OPEN, r.run?.error, r.run?.message && `LAST FIRED: ${r.run.message}`].filter(Boolean).join(" · ") : (r.n?.headline ?? "");
/** The GUI sentence for a script alert. */
const scriptPlain = (s: ScriptAlert) =>
  `Alert when script ${s.script} ${s.cond === null ? "calls alert()" : `says "${s.cond}"`} on ${s.symbol} (runs while OpenTerm is open)`;

const NOTIFY_TEXT: Record<NotifyState, [string, string]> = {
  granted: ["DESKTOP NOTIFICATIONS ON", "up"],
  default: ["DESKTOP NOTIFICATIONS: ASKED WHEN YOU CREATE AN ALERT", "dim"],
  denied: ["DESKTOP NOTIFICATIONS BLOCKED BY THE BROWSER: IN-APP ONLY (STATUS BAR FLASH)", "warn"],
  unsupported: ["NO DESKTOP NOTIFICATIONS IN THIS BROWSER: IN-APP ONLY (STATUS BAR FLASH)", "warn"],
};

const COLUMNS: Column<ARow>[] = [
  { title: "ID", width: 5, align: "right", text: rid, color: () => "dim" },
  { title: "SECURITY", width: 11, text: rsym, color: () => "acc" },
  { title: "CONDITION", width: 20, text: (r) => (r.s ? scriptAlertText(r.s).slice(r.s.symbol.length + 1) : r.n ? `NEWS "${r.n.word}"` : alertText(r.a!).slice(r.a!.symbol.length + 1) + (r.a!.unit === "pct" ? " DAY" : "")) },
  { title: "LAST", width: 11, align: "right", text: (r) => fmtPrice(r.q ? price(r.q) : null), color: (r) => (r.q ? lastColor(r.q) : "fg"), flash: (r, f) => (r.q ? lastFlash(r.q, f) : null) },
  { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(r.q ? pct(r.q) : null), color: (r) => dirColor(r.q ? pct(r.q) : null) },
  { title: "STATUS", width: 10, text: (r) => rstatus(r).toUpperCase(), color: statusColor },
  // the alert's own `VIA` channels; blank = it uses every channel switched on in DELIVERY (a script alert has none: it fires in this tab)
  { title: "DELIVERY", width: 16, text: (r) => (r.s ? "THIS TAB" : viaText((r.a ?? r.n!).channels)), color: () => "dim" },
  { title: "HIT AT", width: 11, align: "right", text: (r) => (r.a?.trigger_price == null ? "" : fmtPrice(r.a.trigger_price)) },
  { title: "HIT TIME", width: 9, align: "right", text: (r) => (rtriggered(r) ? fmtTime(rtriggered(r)! * 1000) : "") },
  { title: "CREATED", width: 9, align: "right", text: (r) => fmtTime(rcreated(r) * 1000), color: () => "dim" },
  { title: "HEADLINE THAT FIRED IT", width: 90, text: rdetail, color: (r) => (r.run?.error ? "err" : "fg") },
];

/** GUI columns: one plain sentence per alert instead of SECURITY + CONDITION codes; no CREATED column. */
const COLUMNS_GUI: Column<ARow>[] = [
  COLUMNS[0],
  { title: "ALERT", width: 52, text: (r) => (r.s ? scriptPlain(r.s) : plainAlert(r.a, r.n)), color: () => "fg" },
  COLUMNS[3],
  COLUMNS[4],
  { title: "STATUS", width: 10, text: (r) => (r.s ? rstatus(r)[0].toUpperCase() + rstatus(r).slice(1) : rstatus(r) === "triggered" ? "Triggered" : "Active"), color: statusColor },
  COLUMNS[6], // DELIVERY (the VIA channels)
  COLUMNS[7],
  COLUMNS[8],
  COLUMNS[10],
];

export default function ALRT({ panelId }: FunctionProps) {
  const list = useStore(alerts, (l) => l);
  const nlist = useStore(newsAlerts, (l) => l);
  const slist = useStore(scriptAlerts, (l) => l);
  const sruns = useStore(scriptAlertRuns, (r) => r);
  const scriptErr = useStore(scriptAlertsError, (e) => e);
  // Either list can fail on its own; both reasons are shown (price alerts first).
  const priceErr = useStore(alertsError, (e) => e);
  const newsErr = useStore(newsAlertsError, (e) => e);
  const err = [priceErr, newsErr].filter(Boolean).join(" · ") || null;
  const notify = useStore(notifyState, (n) => n);
  const engine = useStore(engineState, (s) => s);
  const gui = useStore(settingsStore, (st) => st.mode === "gui");
  const COLS = gui ? COLUMNS_GUI : COLUMNS;
  const [confirm, setConfirm] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);

  useEffect(() => {
    refreshNotifyState();
    void refreshAlerts().catch(failureIsRecorded);
    void refreshNewsAlerts().catch(failureIsRecorded);
    void refreshScriptAlerts(); // records its own failure in scriptAlertsError (its own line below)
    // "last tick N s ago" and the refused-match list change while the panel is open: look every 5 s (one small GET)
    const t = setInterval(() => void refreshEngine(), 5000);
    return () => clearInterval(t);
  }, []);

  const symKey = [...new Set([...(list ?? []).map((a) => a.symbol), ...(slist ?? []).map((s) => s.symbol)])].join(",");
  const inputs = useMemo(() => (symKey ? symKey.split(",") : []), [symKey]);
  const { rows: quotes } = useQuotes(inputs, 0);
  const rows = useMemo<ARow[]>(() => {
    const by = new Map(quotes.map((q) => [q.input, q]));
    return [
      ...(list ?? []).map((a): ARow => ({ a, n: null, s: null, q: by.get(a.symbol) })),
      ...(nlist ?? []).map((n): ARow => ({ a: null, n, s: null })),
      ...(slist ?? []).map((s): ARow => ({ a: null, n: null, s, run: sruns[s.id], q: by.get(s.symbol) })),
    ];
  }, [list, nlist, slist, sruns, quotes]);
  useLiveRows(rows, grid, (r: ARow) => r.a?.symbol ?? r.s?.symbol);
  const latest = useLatest({ rows, confirm });
  useCsvExport(panelId, () => gridCsv("ALRT", COLS, rows));

  usePanelRefresh(panelId, () => { void refreshAlerts().catch(failureIsRecorded); void refreshNewsAlerts().catch(failureIsRecorded); void refreshScriptAlerts(); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, confirm: c } = latest.current;
        const r = cur[g?.selected() ?? -1];
        const confirmKey = r ? `D${rid(r)}` : "";
        if (c && !(c === confirmKey && (e.key === "d" || e.key === "Delete")) && !(c === "CLEAR" && e.key === "c")) setConfirm(null);
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "Enter":
            if (r?.a || r?.s) navigate(panelId, { fn: "GP", security: { symbol: (r.a ?? r.s)!.symbol }, args: ["1D"] });
            else if (r?.n?.url) openExternal(r.n.url);
            else if (r?.n) navigate(panelId, r.n.symbol ? { fn: "N", security: { symbol: r.n.symbol }, args: [] } : { fn: "N", args: [] });
            return true;
          case "n":
          case "a":
            prefillCommand("ALRT ");
            return true;
          case "d":
          case "Delete":
            if (!r) return true;
            if (c === confirmKey) {
              setConfirm(null);
              void (r.a ? deleteAlert(r.a.id) : r.s ? deleteScriptAlert(r.s.id) : deleteNewsAlert(r.n!.id));
            } else setConfirm(confirmKey);
            return true;
          case "r":
            if (r && !r.s && rstatus(r) === "triggered") void (r.a ? rearmAlert(r.a.id) : rearmNewsAlert(r.n!.id));
            return true;
          case "c":
            if (c === "CLEAR") {
              setConfirm(null);
              void clearAlerts();
            } else setConfirm("CLEAR");
            return true;
          case "Escape":
            return c !== null;
        }
        return false;
      }),
    [panelId, latest],
  );

  const all = [...(list ?? []), ...(nlist ?? [])];
  const active = all.filter((a) => a.status === "active").length;
  const [ntext, ncls] = NOTIFY_TEXT[notify];
  const ev = engineView(engine);
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">ALERTS</span> {active} ACTIVE · {all.length - active} TRIGGERED ·{" "}
        <span className={gui ? "legend" : ncls} data-testid="notify-state">{ntext}</span>
        {list === null && !err && <span className="dim"> · LOADING…</span>}
        {err && <span className="err"> · STALE: {err}</span>}
        {slist && slist.length > 0 && <span className="dim"> · {slist.length} SCRIPT ({RUNS_WHILE_OPEN})</span>}
        {confirm === "CLEAR" && <span className="err"> · CLEAR ALL TRIGGERED? PRESS C AGAIN</span>}
        {confirm?.startsWith("D") && <span className="err"> · DELETE ALERT {confirm.slice(1)}? PRESS D AGAIN</span>}
      </div>
      <div className="line" data-testid="alrt-engine">
        <span className={ev.cls}>{ev.head}</span>
        {ev.detail && <span className="dim"> · {ev.detail}</span>}
      </div>
      {ev.skipped.map((s) => (
        <div key={s} className="line warn" data-testid="alrt-skipped">
          NOT FIRED: {s}
        </div>
      ))}
      {gui && notify !== "granted" && (
        // GUI: the browser-permission state is one plain note (not a caption in the header). Only "default" can be asked again.
        <PanelNote
          kind="stale"
          plain={notify === "default" ? "Allow notifications to get a pop-up when an alert fires. Without them it still flashes in the status bar." : "Desktop pop-ups are off, so alerts only flash in the status bar. You can allow them in your browser's site settings."}
          actions={notify === "default" ? [{ label: "Allow notifications", onClick: () => { void Notification.requestPermission().then((p) => notifyState.set(() => p as NotifyState), () => {}); } }] : []}
        >
          {notify === "default" ? "Desktop notifications are not switched on yet." : "Desktop notifications are off."}
        </PanelNote>
      )}
      <div className="dim legend">
        J/K MOVE · ENTER GP · N NEW (ALRT SYM &gt; 200 [VIA TG,EMAIL] | ALRT SYM +5% | ALRT NEWS WORD [SYM]) · D DELETE · R REARM · C CLEAR TRIGGERED · F5 · PRICES CHECKED ON LIVE TICKS AND NEWS WORDS EVERY 2 MIN BY THE OPENTERM SERVER, WITH THIS TAB CLOSED TOO, WHILE OPENTERM RUNS · SCRIPT ALERTS (ALRT AAPL SCRIPT=NAME COND="TITLE", ID SC&lt;N&gt;) {RUNS_WHILE_OPEN}
      </div>
      {scriptErr && (
        <div className="line err" data-testid="alrt-script-err">
          SCRIPT ALERTS: ERR {scriptErr}
        </div>
      )}
      {list?.length === 0 && nlist?.length === 0 && !slist?.length && (
        <PanelNote kind="empty" actions={[{ label: "Add an alert", onClick: () => requestAsk(panelId, "Add an alert") }]} hint="ALRT AAPL > 200, ALRT AAPL -3% (VS PREVIOUS CLOSE), ALRT NEWS RECALL AAPL (HEADLINE HAS THE WORD).">
          NO ALERTS.
        </PanelNote>
      )}
      <Grid ref={grid} columns={COLS} rows={rows} />
      <SmartAlerts />
    </div>
  );
}

/** Phase 27: indicator and drawing alerts (server-side, kept apart from the price grid above). Delete one with ALRT DEL S<id>. */
function SmartAlerts() {
  const [data, setData] = useState<{ indicator: SmartAlert[]; drawing: SmartAlert[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    smartAlertsApi.list().then(setData, (e) => setErr(errText(e)));
  }, []);
  const rows = data ? [...data.indicator, ...data.drawing] : [];
  if (err) return <div className="line err">INDICATOR / DRAWING ALERTS: ERR {err}</div>;
  if (!rows.length) return <div className="dim legend">INDICATOR ALERTS: ALRT AAPL RSI14&lt;30 (COMPLETED DAILY BARS) · DRAWING ALERTS: ALRT AAPL LINE [N] (A GP TREND / RAY / HLINE / CHANNEL)</div>;
  return (
    <div data-testid="alrt-smart">
      <div className="line"><span className="acc">INDICATOR AND DRAWING ALERTS</span> <span className="dim">· ALRT DEL S&lt;ID&gt; DELETES ONE</span></div>
      {rows.map((a) => (
        <div key={a.id} className="line">
          <span className="dim">S{a.id} </span>
          <span className={a.status === "active" ? "up" : "warn"}>{a.status.toUpperCase()} </span>
          {a.type === "ind" ? `${a.symbol} ${a.rule}` : `${a.symbol} ${a.kind === "PCHAN" ? "LEAVES" : "CROSSES"} ${a.kind}`}
          {a.bar ? <span className="dim"> · LAST BAR {a.bar}</span> : null}
          {a.note ? <span className="dim"> · {a.note}</span> : null}
        </div>
      ))}
    </div>
  );
}
