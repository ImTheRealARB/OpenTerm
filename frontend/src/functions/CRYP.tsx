/** Crypto board: CoinGecko top 50 by market cap; Binance 24 h tickers (USDT) when CoinGecko is down. */
import { pollMs } from "../settings/runtime";
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtAge, fmtBig, fmtPct, fmtPrice, fmtTime } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { api, type Coin } from "../net/api";
import { navigate } from "../state/workspace";
import { dirColor, navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { useEnvelope } from "./secPanel";
import { gridCsv, useCsvExport } from "./tableExport";


const COLUMNS: Column<Coin>[] = [
  { title: "#", width: 3, align: "right", text: (r) => (r.rank == null ? "" : String(r.rank)), color: () => "dim" },
  { title: "COIN", width: 6, text: (r) => r.symbol, color: () => "acc" },
  { title: "NAME", width: 16, text: (r) => r.name ?? "", color: () => "dim" },
  { title: "PRICE", width: 13, align: "right", text: (r) => fmtPrice(r.price) },
  { title: "1H%", width: 7, align: "right", text: (r) => fmtPct(r.change_pct_1h), color: (r) => dirColor(r.change_pct_1h) },
  { title: "24H%", width: 7, align: "right", text: (r) => fmtPct(r.change_pct_24h), color: (r) => dirColor(r.change_pct_24h) },
  { title: "7D%", width: 7, align: "right", text: (r) => fmtPct(r.change_pct_7d), color: (r) => dirColor(r.change_pct_7d) },
  { title: "24H HIGH", width: 13, align: "right", text: (r) => fmtPrice(r.high_24h) },
  { title: "24H LOW", width: 13, align: "right", text: (r) => fmtPrice(r.low_24h) },
  { title: "24H VOL", width: 8, align: "right", text: (r) => fmtBig(r.volume_24h) },
  { title: "MKT CAP", width: 8, align: "right", text: (r) => fmtBig(r.market_cap) },
  { title: "UPDATED", width: 8, align: "right", text: (r) => fmtTime(r.updated ? r.updated * 1000 : null), color: () => "dim" },
];

export default function CRYP({ panelId, args }: FunctionProps) {
  const vs = (args[0] ?? "USD").toUpperCase();
  const grid = useRef<GridHandle>(null);

  const { env, error, loading, reload: load } = useEnvelope<{ vs: string; coins: Coin[] }>(vs, (fresh) => api.crypto(vs, fresh));

  useEffect(() => {
    const t = setInterval(() => void load(false), pollMs("crypto"));
    return () => clearInterval(t);
  }, [load]);

  const rows = useMemo(() => env?.data.coins ?? [], [env]);
  const latest = useLatest(rows);
  useCsvExport(panelId, () => gridCsv(`CRYP_${vs}`, COLUMNS, rows));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "Enter": {
            // Charts come from Yahoo's COIN-USD pairs (history is not part of the CoinGecko board).
            const r = cur[g?.selected() ?? -1];
            if (r) navigate(panelId, { fn: "GP", security: { symbol: `${r.symbol}-USD` }, args: [] });
            return true;
          }
          case "F5":
            void load(true);
            return true;
        }
        return false;
      }),
    [panelId, latest, load, vs],
  );

  const quote = rows[0]?.quote ?? vs;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">CRYPTO</span> · PRICES IN {quote}
        {env && ` · ${rows.length} COINS · ${(env.source ?? "").toUpperCase()}`}
        {env && env.fallback_from.length > 0 && <span className="warn"> · FALLBACK (NO RANK OR MARKET CAP)</span>}
        {env && <span className={env.stale ? "warn" : "dim"}> · {env.stale ? "STALE " : "AGE "}{fmtAge(env.age_s)}</span>}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim legend"> · J/K MOVE · ENTER CHART · E CSV · F5 REFRESH</span>
      </div>
      {error && (
        <div className="err">
          {error.message}
          {error.detail && <span className="dim"> ({error.detail})</span>}
          {error.kind === "bad_request" && " · USAGE: CRYP [USD|EUR|INR|GBP|JPY ...]"}
        </div>
      )}
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
