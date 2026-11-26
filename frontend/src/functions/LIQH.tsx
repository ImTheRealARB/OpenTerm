/**
 * LIQH (Phase 23): liquidity heatmap. `LIQH BTCUSDT`: the order book (same source as CDEP, every 5 s) is remembered while
 * the panel is open and drawn as time (left to right) x price (bottom to top); a brighter cell = more resting size there.
 * Memory only, at most 2 hours (`domMath.MAX_SNAPS`): the trade / depth recorder is off (owner decision pending), so
 * closing the panel forgets the history, and the line says how long it has been watching.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { themeColors } from "../chart/chartBase";
import { fmtPrice } from "../format";
import { worldApi } from "../net/worldApi";
import { parseCdepArgs } from "./cryptoArgs";
import { heatGrid, pushSnap, type Snapshot } from "./domMath";
import { usePanelRefresh } from "./panelRefresh";
import { EnvStatus, ErrorLine } from "./panelStatus";
import type { FunctionProps } from "./registry";
import { useEnvelope } from "./useEnvelope";

export default function LIQH({ panelId, args }: FunctionProps) {
  const a = useMemo(() => parseCdepArgs(args), [args]);
  const { env, error, loading, reload } = useEnvelope(a.pair, (fresh) => worldApi.cdep(a.pair, fresh), 5_000);
  const [snaps, setSnaps] = useState<Snapshot[]>([]);
  const cv = useRef<HTMLCanvasElement>(null);
  usePanelRefresh(panelId, () => void reload(true));

  // A new symbol starts a new history; each new book answer adds one column.
  useEffect(() => {
    setSnaps([]);
  }, [a.pair]);
  const d = env?.data;
  useEffect(() => {
    if (d) setSnaps((s) => pushSnap(s, { t: env!.as_of * 1000, bids: d.bids, asks: d.asks }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one column per answer (`d` changes once per fetch)
  }, [d]);

  const heat = useMemo(() => heatGrid(snaps), [snaps]);

  useEffect(() => {
    const c = cv.current;
    if (!c || !heat) return;
    const w = c.clientWidth;
    const h = c.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const col = themeColors();
    ctx.fillStyle = col.bg;
    ctx.fillRect(0, 0, w, h);
    // At least 60 columns wide, so the first few snapshots do not stretch across the whole panel.
    const cw = w / Math.max(60, heat.cells.length);
    const rh = h / heat.rows;
    ctx.fillStyle = col.acc;
    heat.cells.forEach((cells, x) => {
      for (let r = 0; r < heat.rows; r++) {
        if (!cells[r]) continue;
        ctx.globalAlpha = Math.min(1, 0.1 + (0.9 * cells[r]) / heat.max);
        ctx.fillRect(x * cw, h - (r + 1) * rh, Math.ceil(cw), Math.ceil(rh));
      }
    });
    ctx.globalAlpha = 1;
    ctx.fillStyle = col.dim;
    ctx.font = `${col.fs}px ${col.font}`;
    ctx.fillText(fmtPrice(heat.lo + heat.rows * heat.step), 4, col.fs + 2);
    ctx.fillText(fmtPrice(heat.lo), 4, h - 4);
  }, [heat]);

  const minutes = snaps.length > 1 ? Math.round((snaps[snaps.length - 1].t - snaps[0].t) / 60_000) : 0;
  return (
    <div className="fn" style={{ display: "flex", flexDirection: "column" }}>
      <div className="line">
        <span className="acc">LIQH</span> LIQUIDITY HEATMAP · {d ? `${d.symbol} · ${d.venue}` : a.pair}
        <EnvStatus env={env} loading={loading} />
        <span className="dim" data-testid="liqh-count">
          {" "}
          · {snaps.length} SNAPSHOTS OVER {minutes} MIN · KEPT WHILE OPEN ONLY · BRIGHTER = MORE RESTING SIZE
        </span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage="LIQH BTCUSDT" />
      <canvas ref={cv} style={{ flex: 1, minHeight: 120, width: "100%" }} />
    </div>
  );
}
