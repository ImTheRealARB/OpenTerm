/** Insider trades (SEC Form 4, Yahoo as fallback) with buy/sell totals over open-market trades. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type CellColor, type Column, type GridHandle } from "../components/Grid";
import { downloadCsv } from "../csv";
import { fmtBig, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { secApi } from "../net/api";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { ErrorLine, Header, openUrl, useEnvelope } from "./secPanel";
import { fmtShares, insiderTotals, type InsiderTrade, type InsidersPayload } from "./secTables";

const codeColor = (r: InsiderTrade): CellColor => (r.code === "P" ? "up" : r.code === "S" ? "down" : "dim");

const COLUMNS: Column<InsiderTrade>[] = [
  { title: "DATE", width: 10, text: (r) => r.date ?? "", color: () => "dim" },
  { title: "INSIDER", width: 24, text: (r) => r.owner, color: () => "acc" },
  { title: "RELATION", width: 20, text: (r) => r.relation, color: () => "dim" },
  { title: "TRANSACTION", width: 26, text: (r) => (r.derivative ? `${r.code_text} (DERIV)` : r.code_text), color: codeColor },
  { title: "A/D", width: 3, text: (r) => r.acq_disp ?? "", color: codeColor },
  { title: "SHARES", width: 13, align: "right", text: (r) => fmtShares(r.shares) },
  { title: "PRICE", width: 9, align: "right", text: (r) => (r.price == null ? "—" : fmtPrice(r.price)) },
  { title: "VALUE", width: 8, align: "right", text: (r) => (r.value == null ? "—" : fmtBig(r.value)) },
  { title: "OWNED AFTER", width: 13, align: "right", text: (r) => fmtShares(r.owned_after) },
];

export default function OWN({ panelId, security }: FunctionProps) {
  const symbol = security!.symbol;
  const [openOnly, setOpenOnly] = useState(false);
  const grid = useRef<GridHandle>(null);
  const { env, error, loading, reload } = useEnvelope<InsidersPayload>(symbol, (fresh) => secApi.insiders(symbol, fresh));
  const all = useMemo(() => env?.data.trades ?? [], [env]);
  const rows = useMemo(() => (openOnly ? all.filter((t) => t.code === "P" || t.code === "S") : all), [all, openOnly]);
  const totals = useMemo(() => insiderTotals(rows), [rows]);
  const latest = useLatest({ rows });

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current.rows;
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "m":
            setOpenOnly((v) => !v);
            g?.moveTo(0);
            return true;
          case "Enter": {
            const r = cur[g?.selected() ?? -1];
            if (r?.url) openUrl(r.url);
            return true;
          }
          case "e":
            downloadCsv(`OWN_${symbol}`, COLUMNS.map((c) => c.title), cur.map((r) => COLUMNS.map((c) => c.text(r))));
            return true;
          case "F5":
            void reload(true);
            return true;
        }
        return false;
      }),
    [panelId, latest, reload, symbol],
  );

  const d = env?.data;
  return (
    <div className="fn">
      <Header
        title={`OWN ${symbol}${d?.name ? ` · ${d.name.toUpperCase()}` : ""}`}
        env={env}
        loading={loading}
        extra={d && ` · ${rows.length} TRADES${openOnly ? " (OPEN MARKET)" : ""}`}
        keys="J/K MOVE · M OPEN-MARKET ONLY · ENTER FORM 4 · E CSV · F5 REFRESH"
      />
      {d && (
        <div className="line">
          <span className="up">BOUGHT {fmtBig(totals.bought)}</span> · <span className="down">SOLD {fmtBig(totals.sold)}</span>
          <span className="dim"> · OPEN-MARKET P/S TRADES LISTED{d.filings_read != null && ` · ${d.filings_read} FORM 4S READ`}</span>
          {d.failed.length > 0 && <span className="warn"> · {d.failed.length} FORM 4 NOT READ</span>}
        </div>
      )}
      <ErrorLine error={error} hasData={!!env} />
      {d && rows.length === 0 && !error && <div className="warn">NO INSIDER TRADES REPORTED FOR {symbol}</div>}
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
      <div className="summary dim">
        {env?.source === "yahoo_own" ? "YAHOO INSIDER TRANSACTIONS (SEC FORM 4 UNAVAILABLE)" : "SEC FORM 4 · TRANSACTION CODES AS FILED"}
      </div>
    </div>
  );
}
