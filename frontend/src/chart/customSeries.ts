/**
 * Two custom series for lightweight-charts v5 (the library has no built-in series for these shapes):
 *   - `PnfView`       Point and Figure: a real X or O drawn in every box of every column.
 *   - `VolCandleView` Volume candles: a candle whose body is as wide as its volume is large compared with the
 *                     largest volume currently in view.
 *
 * How a custom series works: you give `addCustomSeries` a "pane view" object. The chart calls `update()` with the data and
 * the x position of every point just before painting, then `renderer().draw()` with a canvas and a function that turns a price
 * into a y coordinate. `priceValueBuilder` tells the chart which prices a point covers, so the auto-scale fits them.
 * Docs: lightweight-charts "Custom series" (ICustomSeriesPaneView).
 *
 * The canvas is drawn in "bitmap" pixels (real device pixels), so lines stay sharp on a high-DPI screen: positions the
 * chart gives us are in CSS pixels and are multiplied by `horizontalPixelRatio` / `verticalPixelRatio`.
 */
import {
  customSeriesDefaultOptions,
  type CustomData, type CustomSeriesOptions, type CustomSeriesPricePlotValues, type CustomSeriesWhitespaceData,
  type ICustomSeriesPaneRenderer, type ICustomSeriesPaneView, type PaneRendererCustomData, type Time,
} from "lightweight-charts";

// ---- Point and Figure ------------------------------------------------------------------------------------------------

/** One column: boxes from price `lo` up to price `hi`, X when `up`, else O. */
export interface PnfData extends CustomData<Time> {
  lo: number;
  hi: number;
  up: boolean;
}

export interface PnfOptions extends CustomSeriesOptions {
  /** Colour of the X columns (rising). */
  upColor: string;
  /** Colour of the O columns (falling). */
  downColor: string;
  /** Box size in price units (every box of every column is this tall). */
  box: number;
}

class PnfRenderer implements ICustomSeriesPaneRenderer {
  private _data: PaneRendererCustomData<Time, PnfData> | null = null;
  private _options: PnfOptions | null = null;

  update(data: PaneRendererCustomData<Time, PnfData>, options: PnfOptions): void {
    this._data = data;
    this._options = options;
  }

  draw: ICustomSeriesPaneRenderer["draw"] = (target, priceToCoordinate) => {
    target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hr, verticalPixelRatio: vr, bitmapSize }) => {
      const d = this._data;
      const o = this._options;
      if (!d || !o || !d.visibleRange || !(o.box > 0)) return;
      // A column is one slot wide; the glyph fills 80 % of the slot so neighbours do not touch.
      const slot = d.barSpacing * hr;
      const half = Math.max(1, slot * 0.4);
      const lineW = Math.max(1, Math.round(hr));
      ctx.lineWidth = lineW;
      ctx.lineCap = "butt";
      // One path for all X glyphs and one for all O glyphs: two strokes per frame instead of one per box.
      const xs = new Path2D();
      const os = new Path2D();
      for (let i = d.visibleRange.from; i < d.visibleRange.to; i++) {
        const bar = d.bars[i];
        const col = bar.originalData;
        const cx = bar.x * hr;
        const boxes = Math.round((col.hi - col.lo) / o.box);
        for (let k = 0; k < boxes; k++) {
          // Box edges are converted one by one: on a log price scale the boxes are not equally tall on screen.
          const yTop = priceToCoordinate(col.lo + (k + 1) * o.box);
          const yBot = priceToCoordinate(col.lo + k * o.box);
          if (yTop === null || yBot === null) continue;
          const y0 = yTop * vr;
          const y1 = yBot * vr;
          if (y1 < 0 || y0 > bitmapSize.height) continue; // box is above or below the pane: skip
          const pad = Math.max(1, (y1 - y0) * 0.12);
          if (col.up) {
            xs.moveTo(cx - half, y0 + pad);
            xs.lineTo(cx + half, y1 - pad);
            xs.moveTo(cx + half, y0 + pad);
            xs.lineTo(cx - half, y1 - pad);
          } else {
            const cy = (y0 + y1) / 2;
            const ry = Math.max(1, (y1 - y0) / 2 - pad);
            os.moveTo(cx + half, cy); // start on the ellipse, or the path would draw a line from the last glyph
            os.ellipse(cx, cy, half, ry, 0, 0, Math.PI * 2);
          }
        }
      }
      ctx.strokeStyle = o.upColor;
      ctx.stroke(xs);
      ctx.strokeStyle = o.downColor;
      ctx.stroke(os);
    });
  };
}

export class PnfView implements ICustomSeriesPaneView<Time, PnfData, PnfOptions> {
  private readonly _renderer = new PnfRenderer();

  renderer(): ICustomSeriesPaneRenderer {
    return this._renderer;
  }

  update(data: PaneRendererCustomData<Time, PnfData>, options: PnfOptions): void {
    this._renderer.update(data, options);
  }

  /** The prices a column covers; the last one is where the column currently ends (its top for X, its bottom for O). */
  priceValueBuilder(d: PnfData): CustomSeriesPricePlotValues {
    return d.up ? [d.lo, d.hi] : [d.hi, d.lo];
  }

  isWhitespace(d: PnfData | CustomSeriesWhitespaceData<Time>): d is CustomSeriesWhitespaceData<Time> {
    return (d as PnfData).hi === undefined;
  }

  // The colours and box are always passed by ChartView (theme colours, the box the transform used); these only satisfy the interface.
  defaultOptions(): PnfOptions {
    return { ...customSeriesDefaultOptions, upColor: "#26a69a", downColor: "#ef5350", box: 1 };
  }
}

// ---- Volume candles --------------------------------------------------------------------------------------------------

export interface VolCandleData extends CustomData<Time> {
  open: number;
  high: number;
  low: number;
  close: number;
  /** 0 or NaN = the source has no volume for this bar. */
  vol: number;
}

export interface VolCandleOptions extends CustomSeriesOptions {
  upColor: string;
  downColor: string;
}

class VolCandleRenderer implements ICustomSeriesPaneRenderer {
  private _data: PaneRendererCustomData<Time, VolCandleData> | null = null;
  private _options: VolCandleOptions | null = null;

  update(data: PaneRendererCustomData<Time, VolCandleData>, options: VolCandleOptions): void {
    this._data = data;
    this._options = options;
  }

  draw: ICustomSeriesPaneRenderer["draw"] = (target, priceToCoordinate) => {
    target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
      const d = this._data;
      const o = this._options;
      if (!d || !o || !d.visibleRange) return;
      const from = d.visibleRange.from;
      const to = d.visibleRange.to;
      // The reference for the widths: the largest volume among the bars on screen right now (so zooming re-scales them).
      let vmax = 0;
      for (let i = from; i < to; i++) {
        const v = d.bars[i].originalData.vol;
        if (v > vmax) vmax = v;
      }
      const slot = d.barSpacing * hr;
      const hair = Math.max(1, Math.floor(hr)); // wick and outline thickness
      ctx.lineWidth = hair;
      for (let i = from; i < to; i++) {
        const bar = d.bars[i];
        const c = bar.originalData;
        const yH = priceToCoordinate(c.high);
        const yL = priceToCoordinate(c.low);
        const yO = priceToCoordinate(c.open);
        const yC = priceToCoordinate(c.close);
        if (yH === null || yL === null || yO === null || yC === null) continue;
        const color = c.close >= c.open ? o.upColor : o.downColor;
        const cx = Math.round(bar.x * hr);
        const hasVol = c.vol > 0 && vmax > 0;
        // Body width: volume share of the largest bar in view (at least one pixel). No volume: a normal 70 % slot, drawn hollow.
        const w = hasVol ? Math.max(hair, Math.round(slot * 0.9 * (c.vol / vmax))) : Math.max(hair, Math.round(slot * 0.7));
        const top = Math.round(Math.min(yO, yC) * vr);
        const bottom = Math.round(Math.max(yO, yC) * vr);
        const wickX = cx - Math.floor(hair / 2);
        ctx.fillStyle = color;
        ctx.strokeStyle = color;
        ctx.fillRect(wickX, Math.round(yH * vr), hair, Math.max(hair, Math.round(yL * vr) - Math.round(yH * vr)));
        const bodyH = Math.max(hair, bottom - top);
        if (hasVol) ctx.fillRect(cx - Math.floor(w / 2), top, w, bodyH);
        else ctx.strokeRect(cx - Math.floor(w / 2) + 0.5, top + 0.5, w - 1, bodyH - 1);
      }
    });
  };
}

export class VolCandleView implements ICustomSeriesPaneView<Time, VolCandleData, VolCandleOptions> {
  private readonly _renderer = new VolCandleRenderer();

  renderer(): ICustomSeriesPaneRenderer {
    return this._renderer;
  }

  update(data: PaneRendererCustomData<Time, VolCandleData>, options: VolCandleOptions): void {
    this._renderer.update(data, options);
  }

  priceValueBuilder(d: VolCandleData): CustomSeriesPricePlotValues {
    return [d.high, d.low, d.close];
  }

  isWhitespace(d: VolCandleData | CustomSeriesWhitespaceData<Time>): d is CustomSeriesWhitespaceData<Time> {
    return (d as VolCandleData).close === undefined;
  }

  // ChartView always passes the theme colours; these only satisfy the interface.
  defaultOptions(): VolCandleOptions {
    return { ...customSeriesDefaultOptions, upColor: "#26a69a", downColor: "#ef5350" };
  }
}
