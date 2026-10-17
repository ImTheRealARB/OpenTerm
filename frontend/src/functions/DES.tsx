import { useEffect, useState } from "react";
import { LivePrice } from "../components/LivePrice";
import { fmtAge, fmtBig, fmtNum, fmtPct, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api, type Envelope, type Quote } from "../net/api";
import type { FunctionProps } from "./registry";

interface Profile {
  symbol: string;
  name: string | null;
  exchange: string | null;
  currency: string | null;
  quote_type: string | null;
  sector: string | null;
  industry: string | null;
  country: string | null;
  website: string | null;
  employees: number | null;
  description: string | null;
  market_cap: number | null;
  enterprise_value: number | null;
  pe: number | null;
  forward_pe: number | null;
  eps: number | null;
  forward_eps: number | null;
  dividend_yield: number | null;
  beta: number | null;
  shares_out: number | null;
  float_shares: number | null;
  high_52w: number | null;
  low_52w: number | null;
  avg_volume: number | null;
  price_to_book: number | null;
  delay_min: number | null;
  source: string;
}

type Result<T> = { env?: Envelope<T>; error?: string };

function Range52({ lo, hi, px }: { lo: number | null; hi: number | null; px: number | null }) {
  if (lo == null || hi == null || px == null || hi <= lo) return <span>{fmtPrice(lo)} - {fmtPrice(hi)}</span>;
  const width = 20;
  const pos = Math.max(0, Math.min(width - 1, Math.round(((px - lo) / (hi - lo)) * (width - 1))));
  const bar = "-".repeat(pos) + "|" + "-".repeat(width - 1 - pos);
  return (
    <span>
      {fmtPrice(lo)} <span className="dim">{bar}</span> {fmtPrice(hi)}
    </span>
  );
}

export default function DES({ panelId, security }: FunctionProps) {
  const symbol = security!.symbol;
  const [prof, setProf] = useState<Result<Profile>>({});
  const [quote, setQuote] = useState<Result<Quote>>({});
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let alive = true;
    setProf({});
    setQuote({});
    api.profile(symbol).then(
      (env) => alive && setProf({ env: env as Envelope<Profile> }),
      (e: ApiError) => alive && setProf({ error: e.message }),
    );
    api.quotes([symbol]).then(
      ({ results }) => {
        if (!alive) return;
        const r = Object.values(results)[0];
        setQuote(r && !("error" in r) ? { env: r } : { error: r && "error" in r ? r.error : "NO DATA FOR SYMBOL" });
      },
      (e: ApiError) => alive && setQuote({ error: e.message }),
    );
    return () => {
      alive = false;
    };
  }, [symbol, reload]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.key === "F5") {
          setReload((n) => n + 1);
          return true;
        }
        return false;
      }),
    [panelId],
  );

  const p = prof.env?.data;
  const q = quote.env?.data;
  const name = p?.name ?? q?.name ?? symbol;
  const kv: [string, React.ReactNode][] = p
    ? [
        ["MKT CAP", fmtBig(p.market_cap)],
        ["ENTERPRISE VALUE", fmtBig(p.enterprise_value)],
        ["P/E (TTM)", fmtNum(p.pe)],
        ["P/E (FWD)", fmtNum(p.forward_pe)],
        ["EPS (TTM)", fmtNum(p.eps)],
        ["EPS (FWD)", fmtNum(p.forward_eps)],
        ["DIV YIELD", p.dividend_yield == null ? "—" : fmtPct(p.dividend_yield * 100).replace("+", "")],
        ["BETA", fmtNum(p.beta)],
        ["P/BOOK", fmtNum(p.price_to_book)],
        ["SHARES OUT", fmtBig(p.shares_out)],
        ["FLOAT", fmtBig(p.float_shares)],
        ["AVG VOLUME", fmtBig(p.avg_volume)],
        ["EMPLOYEES", p.employees == null ? "—" : p.employees.toLocaleString("en-US")],
        ["DAY RANGE", q ? `${fmtPrice(q.low)} - ${fmtPrice(q.high)}` : "—"],
      ]
    : [];

  return (
    <div>
      <h2>
        {name} <span className="acc">{symbol}</span>{" "}
        <span className="dim">
          {[p?.exchange ?? q?.exchange, p?.quote_type, p?.currency ?? q?.currency].filter(Boolean).join(" · ")}
        </span>
      </h2>
      {q && quote.env && <LivePrice quote={q} stale={quote.env.stale} ageS={quote.env.age_s} />}
      {quote.error && <div className="err">QUOTE: {quote.error}</div>}
      {!q && !quote.error && <div className="dim">LOADING QUOTE…</div>}
      {p?.delay_min ? <div className="warn">EXCHANGE DATA DELAYED {p.delay_min} MIN (PER SOURCE)</div> : null}

      {p && (
        <>
          <div>
            {[p.sector, p.industry, p.country].filter(Boolean).join(" · ")}
            {p.website && <span className="acc"> · {p.website}</span>}
          </div>
          <div style={{ margin: "4px 0" }}>
            <span className="dim">52W RANGE </span>
            <Range52 lo={p.low_52w ?? q?.low_52w ?? null} hi={p.high_52w ?? q?.high_52w ?? null} px={q?.price ?? null} />
          </div>
          <div className="kv">
            {kv.map(([k, v]) => (
              <div key={k}>
                <span>{k}</span>
                <span>{v}</span>
              </div>
            ))}
          </div>
          {p.description && <div className="desc">{p.description}</div>}
        </>
      )}
      {prof.error && <div className="err">PROFILE: {prof.error}</div>}
      {!p && !prof.error && <div className="dim">LOADING PROFILE…</div>}
      <div className="dim" style={{ marginTop: 6 }}>
        {prof.env && `PROFILE: ${prof.env.source?.toUpperCase()} · ${fmtAge(prof.env.age_s)} OLD${prof.env.stale ? " (STALE)" : ""}`}
        {prof.env?.fallback_from.length ? ` · ${prof.env.fallback_from.join(",").toUpperCase()} DOWN, VIA FALLBACK` : ""}
        {" · F5 REFRESH"}
      </div>
    </div>
  );
}
