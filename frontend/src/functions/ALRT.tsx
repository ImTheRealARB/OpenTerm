/** Alerts: every saved price / percent alert with its live price and state (Phase 8). Evaluation runs app-wide in command/alerts.ts. */
import { useEffect, useMemo, useRef, useState } from "react";
import { alerts, alertsError, alertText, clearAlerts, deleteAlert, deleteNewsAlert, newsAlerts, notifyState, rearmAlert, rearmNewsAlert, refreshAlerts, refreshNewsAlerts, refreshNotifyState, type NotifyState } from "../command/alerts";
import { prefillCommand } from "../components/CommandLine";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtPct, fmtPrice, fmtTime } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import type { Alert, NewsAlert } from "../net/api";
import { useStore } from "../state/store";
import { navigate } from "../state/workspace";
import { dirColor, lastColor, lastFlash, navKey, pct, price, useLatest, useLiveRows, useQuotes, type QRow } from "./quoteRows";
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
  { title: "HIT AT", width: 11, align: "right", text: (r) => (r.a?.trigger_price == null ? "" : fmtPrice(r.a.trigger_price)) },
  { title: "HIT TIME", width: 9, align: "right", text: (r) => (rtriggered(r) ? fmtTime(rtriggered(r)! * 1000) : "") },
  { title: "CREATED", width: 9, align: "right", text: (r) => fmtTime(rcreated(r) * 1000), color: () => "dim" },
  { title: "HEADLINE THAT FIRED IT", width: 90, text: (r) => r.n?.headline ?? "", color: () => "fg" },
];

export default function ALRT({ panelId }: FunctionProps) {
  const list = useStore(alerts, (l) => l);
  const nlist = useStore(newsAlerts, (l) => l);
  const err = useStore(alertsError, (e) => e);
  const notify = useStore(notifyState, (n) => n);
  const [confirm, setConfirm] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);

  useEffect(() => {
    refreshNotifyState();
    void refreshAlerts().catch(() => {});
    void refreshNewsAlerts().catch(() => {});
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
  useCsvExport(panelId, () => gridCsv("ALRT", COLUMNS, rows));

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
          case "F5":
            void refreshAlerts().catch(() => {});
            void refreshNewsAlerts().catch(() => {});
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
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">ALERTS</span> {active} ACTIVE · {all.length - active} TRIGGERED ·{" "}
        <span className={ncls} data-testid="notify-state">{ntext}</span>
        {list === null && !err && <span className="dim"> · LOADING…</span>}
        {err && <span className="err"> · STALE: {err}</span>}
        {confirm === "CLEAR" && <span className="err"> · CLEAR ALL TRIGGERED? PRESS C AGAIN</span>}
        {confirm?.startsWith("D") && <span className="err"> · DELETE ALERT {confirm.slice(1)}? PRESS D AGAIN</span>}
      </div>
      <div className="dim">
        J/K MOVE · ENTER GP · N NEW (ALRT SYM &gt; 200 | ALRT SYM +5% | ALRT NEWS WORD [SYM]) · D DELETE · R REARM · C CLEAR TRIGGERED · F5 · PRICES CHECKED ON LIVE TICKS, NEWS WORDS ON EACH NEWS REFRESH (EVERY 2 MIN) WHILE THIS APP IS OPEN
      </div>
      {list?.length === 0 && nlist?.length === 0 && (
        <div className="dim">NO ALERTS. ALRT AAPL &gt; 200, ALRT AAPL -3% (VS PREVIOUS CLOSE), ALRT NEWS RECALL AAPL (HEADLINE HAS THE WORD).</div>
      )}
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
