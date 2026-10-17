/** Peer comparison: the subject vs its peers (Yahoo recommendations, else largest same-industry names). */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtAge, fmtBig, fmtPct, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api, api9, type Envelope, type PeersPayload, type Quote } from "../net/api";
import { navigate } from "../state/workspace";
import { dirColor, navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { periodReturn } from "./returns";
import { gridCsv, useCsvExport } from "./tableExport";

const PERIODS = [
  { title: "1M%", days: 30 },
  { title: "3M%", days: 91 },
  { title: "6M%", days: 182 },
  { title: "1Y%", days: 365 },
] as const;

interface CompRow {
  role: "SELF" | "PEER" | "MEDIAN";
  symbol: string;
  name: string | null;
  price: number | null;
  pct: number | null;
  cap: number | null;
  rets: (number | null)[];
  note?: string;
}

const median = (xs: (number | null)[]): number | null => {
  const v = xs.filter((x): x is number => x != null).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
};

interface Loaded {
  peers: Envelope<PeersPayload>;
  rows: CompRow[];
  failed: string[];
  stale: boolean;
  age: number;
}

export default function COMP({ panelId, security }: FunctionProps) {
  const symbol = security!.symbol;
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const grid = useRef<GridHandle>(null);

  const load = useCallback(() => {
    setLoading(true);
    return api9
      .peers(symbol)
      .then(async (pe) => {
        const { self, peers } = pe.data;
        const all = [self, ...peers];
        const failed: string[] = [];
        const [qres, hres] = await Promise.all([
          api.quotes(all.map((p) => p.symbol)).catch((e: ApiError) => {
            failed.push(`QUOTES: ${e.message}`);
            return null;
          }),
          Promise.allSettled(all.map((p) => api9.history(p.symbol, "2Y", "1d"))),
        ]);
        let stale = pe.stale;
        let age = pe.age_s;
        const rows: CompRow[] = all.map((p, i) => {
          const qr = qres?.results[p.symbol];
          const q: Quote | null = qr && "data" in qr ? qr.data : null;
          if (qr && "error" in qr) failed.push(`${p.symbol} QUOTE: ${qr.error}`);
          const h = hres[i];
          let rets: (number | null)[] = PERIODS.map(() => null);
          if (h.status === "fulfilled") {
            rets = PERIODS.map((x) => periodReturn(h.value.data, x.days));
            stale = stale || h.value.stale;
            age = Math.max(age, h.value.age_s);
          } else failed.push(`${p.symbol} HISTORY: ${(h.reason as ApiError).message}`);
          return {
            role: i === 0 ? "SELF" : "PEER",
            symbol: p.symbol,
            name: p.name ?? q?.name ?? null,
            price: q?.price ?? null,
            pct: q?.change_pct ?? null,
            cap: p.market_cap,
            rets,
          };
        });
        const peerRows = rows.slice(1);
        if (peerRows.length > 1)
          rows.push({
            role: "MEDIAN", symbol: "MEDIAN", name: `OF ${peerRows.length} PEERS`, price: null,
            pct: median(peerRows.map((r) => r.pct)), cap: median(peerRows.map((r) => r.cap)),
            rets: PERIODS.map((_, k) => median(peerRows.map((r) => r.rets[k]))),
          });
        setData({ peers: pe, rows, failed, stale, age });
        setError(null);
      })
      .catch((e: ApiError) => {
        setData(null);
        setError(e);
      })
      .finally(() => setLoading(false));
  }, [symbol]);

  useEffect(() => {
    setData(null);
    void load();
  }, [load]);

  const rows = useMemo(() => data?.rows ?? [], [data]);
  const latest = useLatest(rows);

  const columns = useMemo<Column<CompRow>[]>(
    () => [
      { title: "ROLE", width: 6, text: (r) => r.role, color: (r) => (r.role === "SELF" ? "warn" : "dim") },
      { title: "SYMBOL", width: 9, text: (r) => r.symbol, color: (r) => (r.role === "MEDIAN" ? "dim" : "acc") },
      { title: "NAME", width: 24, text: (r) => r.name ?? "", color: () => "dim" },
      { title: "PRICE", width: 11, align: "right", text: (r) => (r.role === "MEDIAN" ? "" : fmtPrice(r.price)) },
      { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(r.pct), color: (r) => dirColor(r.pct) },
      { title: "MKT CAP", width: 8, align: "right", text: (r) => fmtBig(r.cap) },
      ...PERIODS.map<Column<CompRow>>((p, k) => ({
        title: p.title, width: 8, align: "right", text: (r) => fmtPct(r.rets[k]), color: (r) => dirColor(r.rets[k]),
      })),
    ],
    [],
  );

  useCsvExport(panelId, () => (rows.length ? gridCsv(`COMP_${symbol}`, columns, rows) : null));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "Enter": {
            const r = cur[g?.selected() ?? -1];
            if (r && r.role !== "MEDIAN") navigate(panelId, { fn: "DES", security: { symbol: r.symbol }, args: [] });
            return true;
          }
          case "F5":
            void load();
            return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  const self = data?.peers.data.self;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">{symbol}</span> · PEERS
        {data && ` · ${data.peers.data.peers.length} FOUND · ${data.peers.data.basis === "yahoo" ? "YAHOO RECOMMENDED" : "SAME INDUSTRY, LARGEST FIRST"}`}
        {data && ` · ${(data.peers.source ?? "").toUpperCase()}`}
        {self?.sector && <span className="dim"> · {self.sector.toUpperCase()}{self.industry ? ` / ${self.industry.toUpperCase()}` : ""}</span>}
        {data && <span className={data.stale ? "warn" : "dim"}> · {data.stale ? "STALE " : "AGE "}{fmtAge(data.age)}</span>}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim"> · J/K MOVE · ENTER DES · E CSV · F5 REFRESH</span>
      </div>
      {error && (
        <div className="err">
          {error.message}
          {error.detail && <span className="dim"> ({error.detail})</span>}
        </div>
      )}
      {data?.failed.map((f) => (
        <div className="warn" key={f}>MISSING: {f}</div>
      ))}
      {data && data.peers.fallback_from.length > 0 && <div className="warn">FALLBACK FROM {data.peers.fallback_from.join(",").toUpperCase()}</div>}
      <Grid ref={grid} columns={columns} rows={rows} />
    </div>
  );
}
