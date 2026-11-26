/**
 * FOOT: footprint chart for crypto (Binance spot trades, exact aggressor side). Drawn by us on one <canvas> (no chart library, no web
 * fonts, colours from the theme's CSS variables, font from `--font`): rows are price levels, columns are bars. Each cell reads
 * "bid x ask" = coins sold into the bid x coins bought at the ask at that price in that bar. A cell with an imbalance (one side at
 * least 3x the other diagonally, see backend `orderflow.footprint`) gets a coloured half. Under the ladder: DELTA (ask - bid) per bar,
 * the cumulative delta number and its line. The bar's busiest price (POC) has a box.
 *
 *   FOOT [SYMBOL] [1M|3M|5M|15M|30M|1H] [BARS]      e.g.  FOOT BTCUSDT 5M 40      BTCUSDT FOOT
 * Keys: h / left, l / right = older / newer bars; j / k or up / down = scroll prices; + / - = column width; 0 = reset; Home / End = oldest / newest.
 * Polls every 5 s. Crypto only (ORDER FLOW: CRYPTO ONLY (BINANCE SPOT PAIRS) for anything else).
 */
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { flowApi } from "../net/flowApi";
import type { FootBar, FootprintPayload } from "../net/flowTypes";
import { recorderApi } from "../net/recorderApi";
import type { RecordedInfo } from "../net/recorderTypes";
import type { Envelope } from "../net/types";
import { displayVersion } from "../settings/runtime";
import { useLatest } from "../state/useLatest";
import { clockMin, fmtSigned, parseFootArgs, serverInterval } from "./flowArgs";
import {
  cellParts, clampBack, COL_CH_DEFAULT, COL_CH_MAX, COL_CH_MIN, columnsFit, FOOTER_ROWS, halfFits, HEADER_ROWS, ladderRows, levelOf,
  levelTop, lineY, stepDecimals, visibleBars, zeroY,
} from "./footMath";
import { usePanelRefresh } from "./panelRefresh";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { RecordedLine } from "./RecordedLine";
import type { FunctionProps } from "./registry";
import { useEnvelope } from "./useEnvelope";

const POLL_MS = 5_000;
const AXIS_CH = 11; // width of the price axis, in characters

interface View {
  /** bars between the newest bar and the newest one on screen */
  back: number;
  /** levels the ladder is scrolled away from centring on the last price (positive = up) */
  shift: number;
  /** column width in characters */
  colCh: number;
}
const VIEW0: View = { back: 0, shift: 0, colCh: COL_CH_DEFAULT };

/** The theme colours the canvas needs, read from CSS variables (the same tokens Grid uses). */
function readColors(el: Element) {
  const cs = getComputedStyle(el);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return {
    bg: v("--bg"), line: v("--line"), fg: v("--val") || v("--fg"), dim: v("--fg-dim"), up: v("--up"), down: v("--down"),
    warn: v("--warn"), acc: v("--accent"), fs: v("--fs"), font: v("--font"), row: parseFloat(v("--row")),
  };
}

export default function FOOT({ panelId, args, security }: FunctionProps) {
  const a = useMemo(() => parseFootArgs(args, security?.symbol), [args, security?.symbol]);
  const key = `${a.rec ?? a.sym}|${a.interval}|${a.bars}`;
  // `REC=<id>`: a recorded session instead of live trades (never changes, so no polling).
  const load = (fresh: boolean): Promise<Envelope<FootprintPayload & { recorded?: RecordedInfo }>> =>
    a.rec ? recorderApi.footprint(a.rec, serverInterval(a.interval), a.bars) : flowApi.footprint(a.sym, serverInterval(a.interval), a.bars, fresh);
  const { env, error, loading, reload } = useEnvelope(key, load, a.rec ? 0 : POLL_MS);
  const d = env?.data;

  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState<View>(VIEW0);
  const [themeTick, bumpTheme] = useReducer((n: number) => n + 1, 0);
  const latest = useLatest({ view, d });

  // A new symbol / interval is a new picture: scroll back to the newest bar.
  useEffect(() => {
    setView((v) => ({ ...v, back: 0, shift: 0 }));
  }, [key]);

  // Canvas size follows its box.
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: Math.floor(el.clientWidth), h: Math.floor(el.clientHeight) }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // A theme / font / number-format change repaints once.
  useEffect(() => displayVersion.subscribe(() => bumpTheme()), []);

  usePanelRefresh(panelId, () => {
    void reload(true);
  });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const set = (f: (v: View) => View) => {
          setView(f);
          return true;
        };
        switch (e.key) {
          case "h":
          case "ArrowLeft":
            return set((v) => ({ ...v, back: v.back + 1 }));
          case "l":
          case "ArrowRight":
            return set((v) => ({ ...v, back: Math.max(0, v.back - 1) }));
          case "Home":
            return set((v) => ({ ...v, back: 1e6 })); // clamped at paint time to the oldest page
          case "End":
            return set((v) => ({ ...v, back: 0 }));
          case "k":
          case "ArrowUp":
            return set((v) => ({ ...v, shift: v.shift + 1 }));
          case "j":
          case "ArrowDown":
            return set((v) => ({ ...v, shift: v.shift - 1 }));
          case "+":
          case "=":
            return set((v) => ({ ...v, colCh: Math.min(COL_CH_MAX, v.colCh + 2) }));
          case "-":
            return set((v) => ({ ...v, colCh: Math.max(COL_CH_MIN, v.colCh - 2) }));
          case "0":
            return set(() => VIEW0);
          default:
            return false;
        }
      }),
    [panelId],
  );

  // Paint. Runs when the data, the view, the size or the theme changes (never per frame: nothing here animates).
  useEffect(() => {
    const cv = canvas.current;
    if (!cv || !d || size.w < 60 || size.h < 60) return;
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.floor(size.w * dpr);
    cv.height = Math.floor(size.h * dpr);
    cv.style.width = `${size.w}px`;
    cv.style.height = `${size.h}px`;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const eff = paintFootprint(ctx, d, latest.current.view, size.w, size.h, readColors(cv));
    // Keys can push the view past either end (Home = "as far back as possible"): store what was really drawn, so the next key starts from it.
    if (eff.back !== view.back || eff.shift !== view.shift) setView((v) => ({ ...v, back: eff.back, shift: eff.shift }));
  }, [d, view, size, themeTick, latest]);

  const last = d?.bars.at(-1);
  const partial = d?.bars[0]?.partial;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">FOOT</span> FOOTPRINT · {d ? `${d.pair} · ${d.interval.toUpperCase()} · ${d.venue}` : `${a.sym} · ${a.interval}`}
        {d && <span className="dim"> · {d.basis}</span>}
        {d?.recorded ? loading && <span className="dim"> · LOADING…</span> : <EnvStatus env={env} loading={loading} />}
        <span className="dim"> · {a.rec ? "" : "5S REFRESH · "}H L BARS · J K PRICES · + - WIDTH · F5</span>
      </div>
      {d?.recorded && <RecordedLine rec={d.recorded} extra={partial ? "FIRST BAR (*) IS PARTIAL: THE RECORDING STARTED INSIDE IT" : undefined} />}
      {a.recError && <div className="line err">{a.recError}</div>}
      {d && (
        <div className="line" data-testid="foot-summary">
          {d.bars.length} BARS ({d.n} TRADES, {Math.round(d.span_s)}S) · STEP {d.step.toFixed(stepDecimals(d.step))}
          {last && (
            <>
              {" "}· LAST <span data-term="DELTA">DELTA</span>{" "}
              <span className={last.delta >= 0 ? "up" : "down"}>{fmtSigned(last.delta)}</span> · CUM <span data-term="DELTA">DELTA</span>{" "}
              <span className={last.cum_delta >= 0 ? "up" : "down"}>{fmtSigned(last.cum_delta)}</span> {d.base}
            </>
          )}
          <span className="dim"> · CELL = BID x ASK COINS · COLOURED HALF = <span data-term="IMBALANCE">IMBALANCE</span> 3:1 · BOX = BUSIEST PRICE</span>
        </div>
      )}
      {d?.truncated && (
        <div className="warn" data-testid="foot-truncated">
          ONLY THE LATEST {Math.round(d.span_s)}S OF TRADES WERE FETCHED (ASKED FOR {d.bars_asked} x {d.interval.toUpperCase()}){partial ? "; THE FIRST BAR (MARKED *) IS PARTIAL" : ""}.
        </div>
      )}
      <ErrorLine error={error} hasData={!!d} usage="FOOT BTCUSDT [1M|3M|5M|15M|30M|1H] [BARS]" />
      <div className="grid" ref={wrap}>
        <canvas ref={canvas} role="img" aria-label={d ? `Footprint of ${d.pair}, ${d.bars.length} bars` : "Footprint"} />
      </div>
    </div>
  );
}

/** Draws the whole footprint. All geometry comes from footMath.ts; this function only turns it into canvas calls. */
function paintFootprint(ctx: CanvasRenderingContext2D, d: FootprintPayload, v: View, w: number, h: number, c: ReturnType<typeof readColors>): { back: number; shift: number } {
  const font = `${c.fs} ${c.font}`;
  ctx.font = font;
  const cw = ctx.measureText("0").width; // one character
  const rowH = c.row > 0 ? c.row : Math.ceil(parseFloat(c.fs) * 1.4);
  const axisPx = AXIS_CH * cw;
  const colPx = v.colCh * cw;

  ctx.fillStyle = c.bg;
  ctx.fillRect(0, 0, w, h);
  if (d.bars.length === 0) return { back: 0, shift: 0 };

  const cols = columnsFit(w, axisPx, colPx);
  const [from, to] = visibleBars(d.bars.length, cols, v.back);
  const bars = d.bars.slice(from, to);
  const rows = ladderRows(h, rowH);
  const anchor = bars.at(-1) as FootBar; // the newest bar on screen decides which price the ladder centres on
  const center = levelOf(anchor.c, d.levels, d.step);
  const top = levelTop(d.levels.length, rows, center, v.shift);
  const shown = Math.min(rows, d.levels.length);
  const dec = stepDecimals(d.step);
  const ladderTop = HEADER_ROWS * rowH;
  const footTop = ladderTop + Math.min(rows, d.levels.length) * rowH;

  ctx.textBaseline = "middle";

  // --- price axis; the row holding the newest bar's close is highlighted ---
  const closeLvl = center;
  ctx.textAlign = "right";
  for (let r = 0; r < Math.min(rows, d.levels.length); r++) {
    const lvl = top - r;
    if (lvl < 0) break;
    ctx.fillStyle = lvl === closeLvl ? c.acc : c.dim;
    ctx.fillText(d.levels[lvl].toFixed(dec), axisPx - cw, ladderTop + r * rowH + rowH / 2);
  }

  // --- columns ---
  const cum: number[] = [];
  bars.forEach((b, i) => {
    const x = axisPx + i * colPx;
    // column divider and time header
    ctx.fillStyle = c.line;
    ctx.fillRect(x, 0, 1, footTop + (FOOTER_ROWS - 3) * rowH);
    ctx.textAlign = "center";
    ctx.fillStyle = b.partial ? c.warn : c.dim;
    ctx.fillText(clockMin(b.t) + (b.partial ? "*" : ""), x + colPx / 2, rowH / 2);

    const byLevel = new Map<number, [number, number, number]>();
    for (const [lvl, bid, ask, flag] of b.cells) byLevel.set(lvl, [bid, ask, flag]);
    const pocLvl = levelOf(b.poc, d.levels, d.step);
    for (let r = 0; r < Math.min(rows, d.levels.length); r++) {
      const lvl = top - r;
      const cell = byLevel.get(lvl);
      if (!cell) continue;
      const [bid, ask, flag] = cell;
      const y = ladderTop + r * rowH;
      // imbalance: the coloured half is the dominant side (left = bid / sellers, right = ask / buyers)
      ctx.globalAlpha = 0.4;
      if (flag & 2) {
        ctx.fillStyle = c.down;
        ctx.fillRect(x + 1, y, colPx / 2 - 1, rowH);
      }
      if (flag & 1) {
        ctx.fillStyle = c.up;
        ctx.fillRect(x + colPx / 2, y, colPx / 2 - 1, rowH);
      }
      ctx.globalAlpha = 1;
      if (lvl === pocLvl) {
        ctx.strokeStyle = c.warn;
        ctx.strokeRect(x + 1.5, y + 0.5, colPx - 3, rowH - 1);
      }
      const parts = cellParts(bid, ask);
      const cx = x + colPx / 2;
      ctx.fillStyle = c.fg;
      if (halfFits(parts.bid.length, v.colCh)) {
        ctx.textAlign = "right";
        ctx.fillText(parts.bid, cx - cw, y + rowH / 2);
      }
      if (halfFits(parts.ask.length, v.colCh)) {
        ctx.textAlign = "left";
        ctx.fillText(parts.ask, cx + cw, y + rowH / 2);
      }
      ctx.textAlign = "center";
      ctx.fillStyle = c.dim;
      ctx.fillText("x", cx, y + rowH / 2);
    }

    // delta rows
    ctx.textAlign = "center";
    ctx.fillStyle = b.delta >= 0 ? c.up : c.down;
    ctx.fillText(fmtSigned(b.delta).length < v.colCh ? fmtSigned(b.delta) : "", x + colPx / 2, footTop + rowH / 2);
    ctx.fillStyle = b.cum_delta >= 0 ? c.up : c.down;
    ctx.fillText(fmtSigned(b.cum_delta).length < v.colCh ? fmtSigned(b.cum_delta) : "", x + colPx / 2, footTop + rowH + rowH / 2);
    cum.push(b.cum_delta);
  });

  // --- footer labels and the cumulative delta line (strip = the last 3 rows) ---
  ctx.textAlign = "right";
  ctx.fillStyle = c.dim;
  ctx.fillText("DELTA", axisPx - cw, footTop + rowH / 2);
  ctx.fillText("CUM DELTA", axisPx - cw, footTop + rowH + rowH / 2);
  const stripTop = footTop + 2 * rowH + 2;
  const stripH = 3 * rowH - 4;
  ctx.fillStyle = c.line;
  ctx.fillRect(axisPx, zeroY(cum, stripTop, stripH), bars.length * colPx, 1); // the zero line
  const ys = lineY(cum, stripTop, stripH);
  ctx.strokeStyle = c.acc;
  ctx.beginPath();
  ys.forEach((y, i) => {
    const px = axisPx + i * colPx + colPx / 2;
    if (i === 0) ctx.moveTo(px, y);
    else ctx.lineTo(px, y);
  });
  ctx.stroke();
  ctx.fillStyle = c.acc;
  ys.forEach((y, i) => ctx.fillRect(axisPx + i * colPx + colPx / 2 - 1.5, y - 1.5, 3, 3));

  // last close, printed in the corner so the axis highlight has a number next to it
  ctx.textAlign = "left";
  ctx.fillStyle = c.acc;
  ctx.fillText(fmtPrice(anchor.c), 2, rowH / 2);
  return { back: clampBack(v.back, d.bars.length, cols), shift: top - (center + Math.floor(shown / 2)) };
}
