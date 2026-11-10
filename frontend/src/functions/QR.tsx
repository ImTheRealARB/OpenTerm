import { useEffect, useState } from "react";
import { LivePrice } from "../components/LivePrice";
import { fmtBig, fmtPrice } from "../format";
import { ApiError } from "../net/core";
import { marketApi } from "../net/marketApi";
import type { Envelope, Quote } from "../net/types";
import type { FunctionProps } from "./registry";

/** Quote recap: one security, live, every quote field we have. */
export default function QR({ security, source }: FunctionProps) {
  const symbol = security!.symbol;
  const [r, setR] = useState<{ env?: Envelope<Quote>; error?: string }>({});

  useEffect(() => {
    let alive = true;
    setR({});
    marketApi.quotes([symbol], source).then(
      ({ results }) => {
        const x = Object.values(results)[0];
        if (alive) setR(x && !("error" in x) ? { env: x } : { error: x && "error" in x ? x.error : "NO DATA FOR SYMBOL" });
      },
      (e: ApiError) => alive && setR({ error: e.message }),
    );
    return () => {
      alive = false;
    };
  }, [symbol, source]);

  if (r.error) return <div className="err">{symbol}: {r.error}</div>;
  if (!r.env) return <div className="dim">LOADING {symbol}…</div>;
  const q = r.env.data;
  const rows: [string, string][] = [
    ["OPEN", fmtPrice(q.open)], ["PREV CLOSE", fmtPrice(q.prev_close)], ["DAY HIGH", fmtPrice(q.high)], ["DAY LOW", fmtPrice(q.low)],
    ["52W HIGH", fmtPrice(q.high_52w)], ["52W LOW", fmtPrice(q.low_52w)], ["VOLUME", fmtBig(q.volume)], ["EXCHANGE", q.exchange ?? "—"],
  ];
  return (
    <div>
      <h2>
        {q.name} <span className="acc">{q.symbol}</span>
      </h2>
      <LivePrice quote={q} stale={r.env.stale} ageS={r.env.age_s} />
      <div className="kv">
        {rows.map(([k, v]) => (
          <div key={k}>
            <span>{k}</span>
            <span>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
