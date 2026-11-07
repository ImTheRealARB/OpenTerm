/** Alerts: every saved price / percent alert with its live price and state (Phase 8). The backend engine fires them (Phase 20); command/alerts.ts shows the result app-wide. */
import { useEffect, useMemo, useRef, useState } from "react";
import { alerts, alertsError, alertText, failureIsRecorded, newsAlertsError, clearAlerts, deleteAlert, deleteNewsAlert, engineState, newsAlerts, notifyState, rearmAlert, rearmNewsAlert, refreshAlerts, refreshEngine, refreshNewsAlerts, refreshNotifyState, type NotifyState } from "../command/alerts";
import { viaText } from "../command/alertArgs";
import { prefillCommand } from "../components/CommandLine";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtPct, fmtPrice, fmtTime } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import type { Alert, NewsAlert } from "../net/types";
import { useStore } from "../state/store";
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

/** A price / percent alert (`a`) or a news keyword alert (`n`, shown with the id N<id>). */
interface ARow {
  a: Alert | null;
  n: NewsAlert | null;
  q?: QRow;
}
const rid = (r: ARow) => (r.a ? String(r.a.id) : `N${r.n!.id}`);
const rsym = (r: ARow) => r.a?.symbol ?? r.n!.symbol ?? "MARKET";
const rstatus = (r: ARow) => (r.a ?? r.n!).status;
const rtriggered = (r: ARow) => (r.a ?? r.n!).triggered_at;
const rcreated = (r: ARow) => (r.a ?? r.n!).created_at;

const NOTIFY_TEXT: Record<NotifyState, [string, string]> = {
  granted: ["DESKTOP NOTIFICATIONS ON", "up"],
  default: ["DESKTOP NOTIFICATIONS: ASKED WHEN YOU CREATE AN ALERT", "dim"],
  denied: ["DESKTOP NOTIFICATIONS BLOCKED BY THE BROWSER: IN-APP ONLY (STATUS BAR FLASH)", "warn"],
  unsupported: ["NO DESKTOP NOTIFICATIONS IN THIS BROWSER: IN-APP ONLY (STATUS BAR FLASH)", "warn"],
};

const COLUMNS: Column<ARow>[] = [
  { title: "ID", width: 5, align: "right", text: rid, color: () => "dim" },
  { title: "SECURITY", width: 11, text: rsym, color: () => "acc" },
  { title: "CONDITION", width: 20, text: (r) => (r.n ? `NEWS "${r.n.word}"` : alertText(r.a!).slice(r.a!.symbol.length + 1) + (r.a!.unit === "pct" ? " DAY" : "")) },
  { title: "LAST", width: 11, align: "right", text: (r) => fmtPrice(r.q ? price(r.q) : null), color: (r) => (r.q ? lastColor(r.q) : "fg"), flash: (r, f) => (r.q ? lastFlash(r.q, f) : null) },
  { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(r.q ? pct(r.q) : null), color: (r) => dirColor(r.q ? pct(r.q) : null) },
  { title: "STATUS", width: 10, text: (r) => rstatus(r).toUpperCase(), color: (r) => (rstatus(r) === "triggered" ? "warn" : "up") },
  // the alert's own `VIA` channels; blank = it uses every channel switched on in DELIVERY
  { title: "DELIVERY", width: 16, text: (r) => viaText((r.a ?? r.n!).channels), color: () => "dim" },
  { title: "HIT AT", width: 11, align: "right", text: (r) => (r.a?.trigger_price == null ? "" : fmtPrice(r.a.trigger_price)) },
  { title: "HIT TIME", width: 9, align: "right", text: (r) => (rtriggered(r) ? fmtTime(rtriggered(r)! * 1000) : "") },
  { title: "CREATED", width: 9, align: "right", text: (r) => fmtTime(rcreated(r) * 1000), color: () => "dim" },
  { title: "HEADLINE THAT FIRED IT", width: 90, text: (r) => r.n?.headline ?? "", color: () => "fg" },
];

/** GUI columns: one plain sentence per alert instead of SECURITY + CONDITION codes; no CREATED column. */
const COLUMNS_GUI: Column<ARow>[] = [
  COLUMNS[0],
  { title: "ALERT", width: 52, text: (r) => plainAlert(r.a, r.n), color: () => "fg" },
  COLUMNS[3],
  COLUMNS[4],
  { title: "STATUS", width: 10, text: (r) => (rstatus(r) === "triggered" ? "Triggered" : "Active"), color: (r) => (rstatus(r) === "triggered" ? "warn" : "up") },
  COLUMNS[6], // DELIVERY (the VIA channels)
  COLUMNS[7],
  COLUMNS[8],
  COLUMNS[10],
];

export default function ALRT({ panelId }: FunctionProps) {
  const list = useStore(alerts, (l) => l);
  const nlist = useStore(newsAlerts, (l) => l);
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
    // "last tick N s ago" and the refused-match list change while the panel is open: look every 5 s (one small GET)
    const t = setInterval(() => void refreshEngine(), 5000);
    return () => clearInterval(t);
  }, []);

  const symKey = [...new Set((list ?? []).map((a) => a.symbol))].join(",");
  const inputs = useMemo(() => (symKey ? symKey.split(",") : []), [symKey]);
  const { rows: quotes } = useQuotes(inputs, 0);
  const rows = useMemo<ARow[]>(() => {
    const by = new Map(quotes.map((q) => [q.input, q]));
    return [
      ...(list ?? []).map((a): ARow => ({ a, n: null, q: by.get(a.symbol) })),
      ...(nlist ?? []).map((n): ARow => ({ a: null, n })),
    ];
  }, [list, nlist, quotes]);
  useLiveRows(rows, grid, (r: ARow) => r.a?.symbol);
  const latest = useLatest({ rows, confirm });
  useCsvExport(panelId, () => gridCsv("ALRT", COLS, rows));

  usePanelRefresh(panelId, () => { void refreshAlerts().catch(failureIsRecorded); void refreshNewsAlerts().catch(failureIsRecorded); });
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
            if (r?.a) navigate(panelId, { fn: "GP", security: { symbol: r.a.symbol }, args: ["1D"] });
            else if (r?.n?.url) window.open(r.n.url, "_blank", "noopener,noreferrer");
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
              void (r.a ? deleteAlert(r.a.id) : deleteNewsAlert(r.n!.id));
            } else setConfirm(confirmKey);
            return true;
          case "r":
            if (r && rstatus(r) === "triggered") void (r.a ? rearmAlert(r.a.id) : rearmNewsAlert(r.n!.id));
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
        J/K MOVE · ENTER GP · N NEW (ALRT SYM &gt; 200 [VIA TG,EMAIL] | ALRT SYM +5% | ALRT NEWS WORD [SYM]) · D DELETE · R REARM · C CLEAR TRIGGERED · F5 · PRICES CHECKED ON LIVE TICKS AND NEWS WORDS EVERY 2 MIN BY THE OPENTERM SERVER, WITH THIS TAB CLOSED TOO, WHILE OPENTERM RUNS
      </div>
      {list?.length === 0 && nlist?.length === 0 && (
        <PanelNote kind="empty" actions={[{ label: "Add an alert", onClick: () => requestAsk(panelId, "Add an alert") }]} hint="ALRT AAPL > 200, ALRT AAPL -3% (VS PREVIOUS CLOSE), ALRT NEWS RECALL AAPL (HEADLINE HAS THE WORD).">
          NO ALERTS.
        </PanelNote>
      )}
      <Grid ref={grid} columns={COLS} rows={rows} />
    </div>
  );
}
