/**
 * Live numbers in plain DOM (the tape and the HOME blocks).
 *
 * The quote grids repaint a canvas on every tick. HOME and the tape are DOM instead, so a tick must change only the text
 * of the few spans that show that symbol, without re-rendering React. How it works:
 *   - each <LiveCell> registers its <span> under the symbol's integer id in ONE module-level map;
 *   - ONE `onTicks` listener (installed when the first cell appears, removed when the last one goes) walks the ids that ticked
 *     in this animation frame and writes the new text into those spans. That is the existing per-frame tick batching,
 *     so a busy market costs a handful of text writes per frame, not a React render.
 */
import { useEffect, useRef } from "react";
import { fmtAge, fmtPct, fmtPrice, sign } from "../format";
import { rowId, type QRow } from "../functions/quoteRows";
import { symId } from "../state/symbols";
import { hasLive, live, onTicks, SRC_SYNTHETIC } from "../state/ticks";

export type CellKind = "last" | "pct";
interface Cell {
  el: HTMLElement;
  kind: CellKind;
}

const cells = new Map<number, Set<Cell>>();
let stopListening: (() => void) | null = null;

/** green / red class for a change (the only meaning colour has here); "" for flat or unknown. */
export const dirClass = (v: number | null | undefined): "up" | "down" | "" => (sign(v) > 0 ? "up" : sign(v) < 0 ? "down" : "");

function paint(c: Cell, id: number): void {
  if (!hasLive(id)) return;
  if (c.kind === "last") {
    c.el.textContent = fmtPrice(live.price[id]);
    return;
  }
  const p = live.pct[id];
  if (p !== p) return; // NaN: this tick did not carry a percent change, keep what is shown
  c.el.textContent = fmtPct(p);
  c.el.classList.remove("up", "down");
  const d = dirClass(p);
  if (d) c.el.classList.add(d);
}

function listen(): void {
  if (stopListening) return;
  stopListening = onTicks((batch) => {
    for (let i = 0; i < batch.count; i++) {
      const set = cells.get(batch.ids[i]);
      if (set) for (const c of set) paint(c, batch.ids[i]);
    }
  });
}

/** Registers `el` to show the live value of `symbol`. Returns the function that unregisters it. */
export function bindCell(symbol: string, kind: CellKind, el: HTMLElement): () => void {
  const id = symId(symbol);
  const cell: Cell = { el, kind };
  let set = cells.get(id);
  if (!set) cells.set(id, (set = new Set()));
  set.add(cell);
  listen();
  paint(cell, id); // a tick may have arrived between the render and this effect
  return () => {
    set.delete(cell);
    if (!set.size) cells.delete(id);
    if (!cells.size && stopListening) {
      stopListening();
      stopListening = null;
    }
  };
}

/** The value a row shows: the live tick if there is one, else the REST snapshot (same rule as the grids). */
function liveOr(r: QRow, which: "price" | "pct"): number | null {
  const id = rowId(r);
  if (hasLive(id)) {
    const v = live[which][id];
    if (v === v) return v;
  }
  return which === "price" ? (r.q?.price ?? null) : (r.q?.change_pct ?? null);
}

export const lastText = (r: QRow | undefined): string => fmtPrice(r ? liveOr(r, "price") : null);
export const pctText = (r: QRow | undefined): string => fmtPct(r ? liveOr(r, "pct") : null);
export const pctClass = (r: QRow | undefined): string => (r ? dirClass(liveOr(r, "pct")) : "");

/** One number that follows the ticks. React renders the first text and class; ticks then overwrite the span in place. */
export function LiveCell({ symbol, kind, row, className = "" }: { symbol: string; kind: CellKind; row: QRow | undefined; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = ref.current;
    return el ? bindCell(symbol, kind, el) : undefined;
  }, [symbol, kind]);
  const cls = kind === "pct" ? `${className} ${pctClass(row)}` : className;
  return (
    <span ref={ref} className={cls.trim()}>
      {kind === "last" ? lastText(row) : pctText(row)}
    </span>
  );
}

/** Why a row's numbers should not be trusted blindly: ERR, SYNTHETIC test data, or a STALE snapshot with its age. Null = fine. */
export function quoteFlag(r: QRow | undefined): { text: string; cls: "err" | "warn" } | null {
  if (!r) return null;
  if (r.error) return { text: "ERR", cls: "err" };
  const id = rowId(r);
  if (hasLive(id) && live.src[id] === SRC_SYNTHETIC) return { text: "SYNTHETIC", cls: "warn" };
  if (r.stale) return { text: `STALE ${fmtAge(r.ageAtFetch + (Date.now() - r.fetchedAt) / 1000)}`, cls: "warn" };
  return null;
}
