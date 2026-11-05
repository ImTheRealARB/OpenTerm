import { useEffect, useState } from "react";
import { LivePrice } from "../components/LivePrice";
import { fmtAge, fmtBig, fmtNum, fmtPct, fmtPrice } from "../format";
import { fallbackText } from "./fallbackText";
import { PanelNote, plainLine, type NoteAction } from "../components/PanelNote";
import { isKeyRequired, KeyRequiredLine } from "./KeyRequiredLine";
import { termProps } from "../gui/term";
import { runSymbol } from "../gui/run";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api, type Envelope, type Quote } from "../net/api";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
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

type Result<T> = { env?: Envelope<T>; error?: string; /** the 424 failure, when the cause is a missing API key */ keyError?: ApiError };

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

/** Row label on the screen -> glossary term (see gui/glossary.ts) shown as a tooltip in GUI mode. */
const TERM_OF: Record<string, string> = {
  "MKT CAP": "MARKET CAP",
  "ENTERPRISE VALUE": "ENTERPRISE VALUE",
  "P/E (TTM)": "P/E",
  "P/E (FWD)": "FORWARD P/E",
  "EPS (TTM)": "EPS",
  "EPS (FWD)": "FORWARD EPS",
  "DIV YIELD": "DIVIDEND YIELD",
  "BETA": "BETA",
  "P/BOOK": "P/B",
  "SHARES OUT": "SHARES OUTSTANDING",
  "FLOAT": "FLOAT",
  "AVG VOLUME": "AVG VOLUME",
  "DAY RANGE": "DAY RANGE",
};

/** GUI-only plain labels for the ratio rows (Terminal keeps the codes). */
const GUI_LABEL: Record<string, string> = {
  "P/E (TTM)": "P/E, last 12 months",
  "P/E (FWD)": "P/E, next 12 months",
  "EPS (TTM)": "EPS, last 12 months",
  "EPS (FWD)": "EPS, next 12 months",
};

/**
 * The company blurb. In GUI mode a long one is clamped to about four lines (CSS `.desc-clamp`) with a "Read more"
 * button (a real <button>, so Tab and Enter work). Terminal shows the whole text, as before.
 */
function Description({ text, gui }: { text: string; gui: boolean }) {
  const [open, setOpen] = useState(false);
  const long = gui && text.length > 280;
  return (
    <>
      <div className={long && !open ? "desc desc-clamp" : "desc"}>{text}</div>
      {long && (
        <button type="button" className="desc-more" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Show less" : "Read more"}
        </button>
      )}
    </>
  );
}

export default function DES({ panelId, security }: FunctionProps) {
  const symbol = security!.symbol;
  const gui = useStore(settingsStore, (s) => s.mode === "gui");
  const [prof, setProf] = useState<Result<Profile>>({});
  const [quote, setQuote] = useState<Result<Quote>>({});
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let alive = true;
    setProf({});
    setQuote({});
    api.profile(symbol).then(
      (env) => alive && setProf({ env: env as Envelope<Profile> }),
      (e: ApiError) => alive && setProf({ error: e.message, keyError: isKeyRequired(e) ? e : undefined }),
    );
    api.quotes([symbol]).then(
      ({ results }) => {
        if (!alive) return;
        const r = Object.values(results)[0];
        setQuote(r && !("error" in r) ? { env: r } : { error: r && "error" in r ? r.error : "NO DATA FOR SYMBOL" });
      },
      (e: ApiError) => alive && setQuote({ error: e.message, keyError: isKeyRequired(e) ? e : undefined }),
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

  // Unknown symbol (GUI mode): both requests said "no data". Offer the closest company names as one-click next steps.
  const noData = (e?: string) => !!e && /NO DATA|NOT FOUND/i.test(e);
  const unknown = gui && noData(quote.error) && noData(prof.error);
  const [near, setNear] = useState<NoteAction[]>([]);
  useEffect(() => {
    if (!unknown) {
      setNear([]);
      return;
    }
    let alive = true;
    // The stock list is loaded only now (import + fetch), never at startup.
    void import("../gui/suggestData")
      .then((m) => m.closest(symbol))
      .then((hits) => alive && setNear(hits.map((h) => ({ label: `Try ${h.symbol}`, onClick: () => void runSymbol(h.symbol) }))))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [unknown, symbol]);

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
      {quote.env?.fallback_from.length ? <div className="warn">QUOTE: {fallbackText(quote.env.fallback_from, quote.env.fallback_notes)}</div> : null}
      {quote.keyError && <KeyRequiredLine error={quote.keyError} />}
      {quote.error && !quote.keyError && <div className="err">QUOTE: {quote.error}</div>}
      {gui && quote.error && !unknown && prof.error && (
        <PanelNote kind="error" plain={plainLine("error", `${quote.error} ${prof.error}`)} onRetry={() => setReload((n) => n + 1)}>
          Could not load this stock.
        </PanelNote>
      )}
      {!q && !quote.error && <div className="dim">LOADING QUOTE…</div>}
      {p?.delay_min ? (
        gui ? <div className="des-delay dim">Prices from the exchange are delayed {p.delay_min} min (per source).</div> : <div className="warn">EXCHANGE DATA DELAYED {p.delay_min} MIN (PER SOURCE)</div>
      ) : null}

      {p && (
        <>
          <div>
            {[p.sector, p.industry, p.country].filter(Boolean).join(" · ")}
            {p.website && <span className="acc"> · {p.website}</span>}
          </div>
          <div style={{ margin: "4px 0" }}>
            <span className="dim" {...termProps("52-WEEK RANGE", gui)}>52W RANGE </span>
            <Range52 lo={p.low_52w ?? q?.low_52w ?? null} hi={p.high_52w ?? q?.high_52w ?? null} px={q?.price ?? null} />
          </div>
          <div className="kv">
            {kv.map(([k, v]) => (
              <div key={k}>
                <span {...(TERM_OF[k] ? termProps(TERM_OF[k], gui) : {})}>{gui ? (GUI_LABEL[k] ?? k) : k}</span>
                <span>{v}</span>
              </div>
            ))}
          </div>
          {p.description && <Description text={p.description} gui={gui} />}
        </>
      )}
      {prof.keyError && !quote.keyError && <KeyRequiredLine error={prof.keyError} />}
      {prof.error && !prof.keyError && <div className="err">PROFILE: {prof.error}</div>}
      {unknown && (
        <PanelNote kind="error" plain="" actions={near}>
          {`There is no stock called ${symbol}.`}
        </PanelNote>
      )}
      {!p && !prof.error && <div className="dim">LOADING PROFILE…</div>}
      <div className="dim" style={{ marginTop: 6 }}>
        {prof.env && `PROFILE: ${prof.env.source?.toUpperCase()} · ${fmtAge(prof.env.age_s)} OLD${prof.env.stale ? " (STALE)" : ""}`}
        {prof.env?.fallback_from.length ? ` · ${fallbackText(prof.env.fallback_from, prof.env.fallback_notes)}` : ""}
        {" · F5 REFRESH"}
      </div>
    </div>
  );
}
