/** Alerts: every saved price / percent alert with its live price and state (Phase 8). Evaluation runs app-wide in command/alerts.ts. */
import { useEffect, useMemo, useRef, useState } from "react";
import { alerts, alertsError, alertText, clearAlerts, deleteAlert, notifyState, rearmAlert, refreshAlerts, refreshNotifyState, type NotifyState } from "../command/alerts";
import { prefillCommand } from "../components/CommandLine";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtPct, fmtPrice, fmtTime } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import type { Alert } from "../net/api";
import { useStore } from "../state/store";
import { navigate } from "../state/workspace";
import { dirColor, lastColor, lastFlash, navKey, pct, price, useLatest, useLiveRows, useQuotes, type QRow } from "./quoteRows";
import type { FunctionProps } from "./registry";

interface ARow {
  a: Alert;
  q?: QRow;
}

const NOTIFY_TEXT: Record<NotifyState, [string, string]> = {
  granted: ["DESKTOP NOTIFICATIONS ON", "up"],
  default: ["DESKTOP NOTIFICATIONS: ASKED WHEN YOU CREATE AN ALERT", "dim"],
  denied: ["DESKTOP NOTIFICATIONS BLOCKED BY THE BROWSER: IN-APP ONLY (STATUS BAR FLASH)", "warn"],
  unsupported: ["NO DESKTOP NOTIFICATIONS IN THIS BROWSER: IN-APP ONLY (STATUS BAR FLASH)", "warn"],
};

const COLUMNS: Column<ARow>[] = [
  { title: "ID", width: 4, align: "right", text: (r) => String(r.a.id), color: () => "dim" },
  { title: "SECURITY", width: 11, text: (r) => r.a.symbol, color: () => "acc" },
  { title: "CONDITION", width: 12, text: (r) => alertText(r.a).slice(r.a.symbol.length + 1) + (r.a.unit === "pct" ? " DAY" : "") },
  { title: "LAST", width: 11, align: "right", text: (r) => fmtPrice(r.q ? price(r.q) : null), color: (r) => (r.q ? lastColor(r.q) : "fg"), flash: (r, f) => (r.q ? lastFlash(r.q, f) : null) },
  { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(r.q ? pct(r.q) : null), color: (r) => dirColor(r.q ? pct(r.q) : null) },
  { title: "STATUS", width: 10, text: (r) => r.a.status.toUpperCase(), color: (r) => (r.a.status === "triggered" ? "warn" : "up") },
  { title: "HIT AT", width: 11, align: "right", text: (r) => (r.a.trigger_price == null ? "" : fmtPrice(r.a.trigger_price)) },
  { title: "HIT TIME", width: 9, align: "right", text: (r) => (r.a.triggered_at ? fmtTime(r.a.triggered_at * 1000) : "") },
  { title: "CREATED", width: 9, align: "right", text: (r) => fmtTime(r.a.created_at * 1000), color: () => "dim" },
];

export default function ALRT({ panelId }: FunctionProps) {
  const list = useStore(alerts, (l) => l);
  const err = useStore(alertsError, (e) => e);
  const notify = useStore(notifyState, (n) => n);
  const [confirm, setConfirm] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);

  useEffect(() => {
    refreshNotifyState();
    void refreshAlerts().catch(() => {});
  }, []);

  const symKey = [...new Set((list ?? []).map((a) => a.symbol))].join(",");
  const inputs = useMemo(() => (symKey ? symKey.split(",") : []), [symKey]);
  const { rows: quotes } = useQuotes(inputs, 0);
  const rows = useMemo<ARow[]>(() => {
    const by = new Map(quotes.map((q) => [q.input, q]));
    return (list ?? []).map((a) => ({ a, q: by.get(a.symbol) }));
  }, [list, quotes]);
  useLiveRows(rows, grid, (r: ARow) => r.a.symbol);
  const latest = useLatest({ rows, confirm });

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: cur, confirm: c } = latest.current;
        const r = cur[g?.selected() ?? -1];
        const confirmKey = r ? `D${r.a.id}` : "";
        if (c && !(c === confirmKey && (e.key === "d" || e.key === "Delete")) && !(c === "CLEAR" && e.key === "c")) setConfirm(null);
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "Enter":
            if (r) navigate(panelId, { fn: "GP", security: { symbol: r.a.symbol }, args: ["1D"] });
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
              void deleteAlert(r.a.id);
            } else setConfirm(confirmKey);
            return true;
          case "r":
            if (r && r.a.status === "triggered") void rearmAlert(r.a.id);
            return true;
          case "c":
            if (c === "CLEAR") {
              setConfirm(null);
              void clearAlerts();
            } else setConfirm("CLEAR");
            return true;
          case "F5":
            void refreshAlerts().catch(() => {});
            return true;
          case "Escape":
            return c !== null;
        }
        return false;
      }),
    [panelId, latest],
  );

  const active = (list ?? []).filter((a) => a.status === "active").length;
  const [ntext, ncls] = NOTIFY_TEXT[notify];
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">ALERTS</span> {active} ACTIVE · {(list?.length ?? 0) - active} TRIGGERED ·{" "}
        <span className={ncls} data-testid="notify-state">{ntext}</span>
        {list === null && !err && <span className="dim"> · LOADING…</span>}
        {err && <span className="err"> · STALE: {err}</span>}
        {confirm === "CLEAR" && <span className="err"> · CLEAR ALL TRIGGERED? PRESS C AGAIN</span>}
        {confirm?.startsWith("D") && <span className="err"> · DELETE ALERT {confirm.slice(1)}? PRESS D AGAIN</span>}
      </div>
      <div className="dim">
        J/K MOVE · ENTER GP · N NEW (ALRT SYM &gt; 200 | ALRT SYM +5%) · D DELETE · R REARM · C CLEAR TRIGGERED · F5 · CHECKED ON LIVE TICKS WHILE THIS APP IS OPEN (ANY PANEL, ALSO IN A BACKGROUND TAB)
      </div>
      {list?.length === 0 && <div className="dim">NO ALERTS. ALRT AAPL &gt; 200, ALRT AAPL -3% (VS PREVIOUS CLOSE).</div>}
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
