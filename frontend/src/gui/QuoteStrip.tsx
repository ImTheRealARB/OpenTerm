import { useEffect, useMemo, useRef } from "react";
import { fmtAge, fmtBig, fmtChg, fmtPct, fmtPrice, fmtTime } from "../format";
import { chg, high, low, pct, price, quoteTime, vol, type QRow, useQuotes } from "../functions/quoteRows";
import { subscribe } from "../net/socket";
import { symId } from "../state/symbols";
import { hasLive, live, onTicks, srcLabel } from "../state/ticks";

/**
 * GUI-only "quote line" under a panel's button row: the security, its price and change, and the day's range, in one line.
 *
 *   AAPL  Apple Inc.   349.50  +17.60  +5.30%    Open 335.10  High 354.47  Low 340.99  Volume 88.96M   LIVE STREAM 14:45
 *
 * Why it exists: a beginner looking at a chart or a statement should always see the live price without opening another panel.
 * Data: one REST snapshot (`useQuotes`, the same call every quote grid uses) and then live ticks.
 * Ticks repaint the TEXT NODES directly (the pattern of components/LivePrice.tsx), so a tick never causes a React render.
 *
 * Honesty rule (CLAUDE.md "Never fake data"): when the snapshot failed the line says ERR with the reason, and a snapshot that
 * is old says STALE with its age and source. Nothing is ever filled in with a made-up number.
 */
export function QuoteStrip({ symbol }: { symbol: string }) {
  const inputs = useMemo(() => [symbol], [symbol]);
  const { rows, loading } = useQuotes(inputs, 0);
  const row: QRow | undefined = rows[0];

  // One element per piece of the line; `paint` fills them. Kept in one object so the effect below stays short.
  const el = useRef<Record<string, HTMLSpanElement | null>>({});
  const set = (k: string) => (n: HTMLSpanElement | null) => void (el.current[k] = n);

  // The WebSocket subscription is per symbol, as in LivePrice (not per snapshot refresh).
  useEffect(() => subscribe([symbol]), [symbol]);

  useEffect(() => {
    if (!row) return;
    const e = el.current;
    const text = (k: string, v: string, cls = "") => {
      const n = e[k];
      if (!n) return;
      if (n.textContent !== v) n.textContent = v;
      if (n.className !== cls) n.className = cls;
    };
    const paint = () => {
      const q = row.q;
      const id = symId(symbol);
      const isLive = hasLive(id);
      if (row.error || !q) {
        // The failure is shown as it is: the server's message, never a substitute number.
        text("px", "");
        text("chg", "");
        text("pct", "");
        text("ohlv", "");
        text("src", row.error ? `ERR ${row.error}` : loading ? "Loading..." : "ERR no quote", row.error ? "err" : "dim");
        return;
      }
      const c = chg(row);
      const cls = (c ?? 0) > 0 ? "up" : (c ?? 0) < 0 ? "down" : "";
      const arrow = (c ?? 0) > 0 ? "▲ " : (c ?? 0) < 0 ? "▼ " : "";
      text("px", fmtPrice(price(row)), "qs-px " + cls);
      text("chg", arrow + fmtChg(c), cls);
      text("pct", fmtPct(pct(row)), cls);
      const open = q.open != null ? `Open ${fmtPrice(q.open)}  ` : "";
      text("ohlv", `${open}High ${fmtPrice(high(row))}  Low ${fmtPrice(low(row))}  Volume ${fmtBig(vol(row))}`, "qs-ohlv");
      // Source: LIVE (with the stream's name) or the REST snapshot's source, marked STALE with its age when it is old.
      const t = fmtTime(quoteTime(row));
      if (isLive) text("src", `LIVE ${srcLabel(live.src[id])} ${t}`, live.src[id] === 115 /* "s" = SYNTHETIC */ ? "warn" : "up");
      else {
        const age = row.ageAtFetch + (Date.now() - row.fetchedAt) / 1000;
        text("src", row.stale ? `STALE ${fmtAge(age)} · ${(q.source ?? "").toUpperCase()}` : `${(q.source ?? "").toUpperCase()} ${t}`, row.stale ? "warn" : "dim");
      }
    };
    paint();
    const sid = symId(symbol);
    const off = onTicks((batch) => {
      if (batch.has(sid)) paint();
    });
    // The STALE age keeps counting, so repaint every 10 s while nothing ticks.
    const timer = window.setInterval(paint, 10_000);
    return () => {
      off();
      window.clearInterval(timer);
    };
  }, [row, loading, symbol]);

  const q = row?.q;
  return (
    <div className="qs" data-testid="quote-strip">
      <span className="qs-sym">{symbol}</span>
      {q?.name && <span className="qs-name">{q.name}</span>}
      <span ref={set("px")} />
      <span ref={set("chg")} />
      <span ref={set("pct")} />
      <span ref={set("ohlv")} />
      <span className="qs-fill" />
      <span ref={set("src")} />
    </div>
  );
}
