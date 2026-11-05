/**
 * The ticker tape: one thin strip of "LABEL  last  +0.42%" items scrolling right to left.
 *
 * Motion: the items are drawn twice, side by side, inside one track; a single CSS animation slides the track left by exactly
 * half its width and repeats, so the second copy lands where the first started and the loop has no seam. That is one
 * transform animation for the whole strip (no JS timer, no per-item work). It pauses on hover and while the tab is hidden,
 * and `prefers-reduced-motion` turns the animation off (the strip then scrolls by hand). See home.css.
 *
 * Numbers follow the live ticks through LiveCell; STALE / SYNTHETIC / ERR show per item (quoteFlag). Nothing is invented:
 * an item with no data yet shows a dash.
 */
import { useEffect, useRef, type CSSProperties } from "react";
import type { QRow } from "../functions/quoteRows";
import { tapeLabel } from "./homeConfig";
import { LiveCell, quoteFlag } from "./liveCells";
import "./home.css";

/** Seconds of scrolling per item: about 50 px a second, slow enough to read. */
const SECONDS_PER_ITEM = 3;

function TapeItem({ symbol, row }: { symbol: string; row: QRow | undefined }) {
  const flag = quoteFlag(row);
  return (
    <span className="tp" data-sym={symbol} title={row?.error ?? row?.q?.name ?? symbol}>
      <b className="tp-l">{tapeLabel(symbol)}</b> <LiveCell symbol={symbol} kind="last" row={row} className="tp-v" />{" "}
      <LiveCell symbol={symbol} kind="pct" row={row} />
      {flag && <span className={flag.cls}> {flag.text}</span>}
    </span>
  );
}

export function TickerTape({ symbols, quotes }: { symbols: readonly string[]; quotes: ReadonlyMap<string, QRow> }) {
  const root = useRef<HTMLDivElement>(null);
  // Stop animating while the tab is hidden (nobody sees it); the browser would pause the paint anyway, this also stops the clock.
  useEffect(() => {
    const sync = () => {
      root.current?.toggleAttribute("data-paused", document.hidden);
    };
    sync();
    document.addEventListener("visibilitychange", sync);
    return () => document.removeEventListener("visibilitychange", sync);
  }, []);

  if (!symbols.length) {
    return (
      <div className="tape dim" data-testid="tape">
        TAPE EMPTY: TAPE ADD SYM (OR TAPE RESET)
      </div>
    );
  }
  const half = (copy: boolean) => (
    <div className="tape-half" aria-hidden={copy || undefined}>
      {symbols.map((s) => (
        <TapeItem key={s} symbol={s} row={quotes.get(s)} />
      ))}
    </div>
  );
  return (
    <div className="tape" ref={root} data-testid="tape" style={{ "--tape-dur": `${symbols.length * SECONDS_PER_ITEM}s` } as CSSProperties}>
      <div className="tape-track">
        {half(false)}
        {half(true)}
      </div>
    </div>
  );
}
