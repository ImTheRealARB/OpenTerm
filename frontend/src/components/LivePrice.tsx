import { useEffect, useRef } from "react";
import { fmtChg, fmtPct, fmtPrice, fmtTime } from "../format";
import type { Quote } from "../net/types";
import { subscribe } from "../net/socket";
import { symId } from "../state/symbols";
import { getLive, onTicks, SRC_LABEL } from "../state/ticks";

/**
 * Big live price line. Updates its own text nodes on ticks: no React render per tick.
 */
export function LivePrice({ quote, stale, ageS }: { quote: Quote; stale: boolean; ageS: number }) {
  const px = useRef<HTMLSpanElement>(null);
  const ch = useRef<HTMLSpanElement>(null);
  const tm = useRef<HTMLSpanElement>(null);
  const src = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const paint = () => {
      const l = getLive(quote.symbol);
      const price = l?.price ?? quote.price;
      const change = l?.change ?? quote.change;
      const pct = l?.pct ?? quote.change_pct;
      const cls = (change ?? 0) > 0 ? "up" : (change ?? 0) < 0 ? "down" : "";
      px.current!.textContent = fmtPrice(price);
      px.current!.className = "big " + (l ? (l.dir > 0 ? "up" : l.dir < 0 ? "down" : "") : "");
      ch.current!.textContent = `${fmtChg(change)}  ${fmtPct(pct)}`;
      ch.current!.className = cls;
      tm.current!.textContent = fmtTime(l?.t ?? (quote.market_time ? quote.market_time * 1000 : null));
      src.current!.textContent = l ? `LIVE ${SRC_LABEL[l.src] ?? l.src}` : stale ? `STALE (${Math.round(ageS)}S OLD)` : (quote.source ?? "").toUpperCase();
      src.current!.className = l ? (l.src === "s" ? "warn" : "up") : stale ? "warn" : "dim";
    };
    paint();
    const id = symId(quote.symbol); // intern once; the per-frame check is then one bit test
    return onTicks((batch) => {
      if (batch.has(id)) paint();
    });
  }, [quote, stale, ageS]);

  // Subscribed per symbol, not per quote refresh: a refresh used to send unsub then sub for the same symbol.
  const symbol = quote.symbol;
  useEffect(() => subscribe([symbol]), [symbol]);

  return (
    <div className="line">
      <span ref={px} className="big" /> <span ref={ch} /> <span className="dim">{quote.currency}</span>{" "}
      <span ref={tm} className="dim" /> <span ref={src} />
    </div>
  );
}
