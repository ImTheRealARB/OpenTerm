/**
 * The IMAP heat map itself: layout, painting, selection, keys, legend, CSV. It knows nothing about where the rows came from
 * (equities, crypto, ETFs): the caller hands it an `ImapView` (imapUniverses.ts) and the words for its title line.
 * Layout and colour bands are pure (treemap.ts); painting is one canvas pass (imapPaint.ts).
 * Keys: arrows / H J K L move between tiles, Enter opens Q, Z zooms into the group, Backspace zooms out, E exports CSV, F5 refreshes
 * (the caller registers F5 with `usePanelRefresh`).
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { fmtBig, fmtPct } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { gauges } from "../perf/metrics";
import { displayVersion } from "../settings/runtime";
import { useStore } from "../state/store";
import { navigate } from "../state/workspace";
import { useLatest } from "../state/useLatest";
import { BAND_ALPHA, BAND_LABELS, paintTreemap, type PaintColors } from "./imapPaint";
import type { ImapView } from "./imapUniverses";
import { gridCsv, useCsvExport } from "./tableExport";
import { neighbor, treemap, type Dir } from "./treemap";

function themeColors(): PaintColors {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return { bg: v("--bg"), fg: v("--fg"), dim: v("--fg-dim"), up: v("--up"), down: v("--down"), sel: v("--sel"), line: v("--line"), font: v("--font") };
}

export interface ImapBoardProps {
  panelId: number;
  /** The word after IMAP in the title: SECTOR, INDUSTRY, COUNTRY, CRYPTO, ETF. */
  label: string;
  /** Filter words the user typed, shown after the label. */
  rest: string[];
  view: ImapView | null;
  /** What a tile's size means ("MARKET CAP", "TOTAL ASSETS"), its short column title and its short readout word. */
  sizeWord: string;
  sizeTitle: string;
  /** Readout label before the size ("MCAP"); "" hides the size (IMAP NIFTY's tiles are equal, so their size means nothing). */
  sizeShort: string;
  /** What the colour means; the default is the day's change. */
  colourWord?: string;
  csvName: string;
  /** The caller's data status for the title line (source, age, LOADING...). */
  status: ReactNode;
  /** The caller's own lines under the title (data still loading, quotes missing...). */
  notes?: ReactNode;
  /** Wording for rows that have no size, and the N that cut the map. */
  noSizeText: string;
  limit: number;
  /** Changes when a different command is typed, so a zoomed group is dropped. */
  argsKey: string;
}

export function ImapBoard(p: ImapBoardProps) {
  const { panelId, view } = p;
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [selId, setSelId] = useState<number | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const ver = useStore(displayVersion, (v) => v);
  const colors = useRef<PaintColors | null>(null);

  useEffect(() => {
    setZoom(null);
  }, [p.argsKey]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: Math.floor(el.clientWidth), h: Math.floor(el.clientHeight) }));
    ro.observe(el);
    setSize({ w: Math.floor(el.clientWidth), h: Math.floor(el.clientHeight) });
    return () => ro.disconnect();
  }, []);

  const layout = useMemo(() => {
    if (!view || !size || size.w < 20 || size.h < 20) return null;
    const groups = zoom ? view.groups.filter((g) => g.key === zoom) : view.groups;
    const t0 = performance.now();
    const l = treemap(groups, size.w, size.h, { header: 14, pad: 1 });
    gauges.set("imap.layoutMs", performance.now() - t0);
    gauges.set("imap.tiles", l.tiles.length);
    return { ...l, groupKeys: groups.map((g) => g.key) };
  }, [view, size, zoom]);

  const paintRows = useMemo(() => (view ? view.rows.map((r) => ({ sym: r.sym, pct: r.pct })) : []), [view]);
  const live = useLatest({ layout, view, selId, zoom });

  // Keep the selection on a visible tile (the biggest one) when the data, filter or zoom changes.
  useEffect(() => {
    if (!layout) return;
    if (selId === null || !layout.tiles.some((t) => t.id === selId)) setSelId(layout.tiles[0]?.id ?? null);
  }, [layout, selId]);

  useEffect(() => {
    const cv = canvas.current;
    if (!cv || !layout || !size) return;
    colors.current = themeColors();
    const dpr = window.devicePixelRatio || 1;
    cv.width = Math.round(size.w * dpr);
    cv.height = Math.round(size.h * dpr);
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const t0 = performance.now();
    paintTreemap(ctx, size.w, size.h, layout, paintRows, colors.current, selId);
    gauges.set("imap.paintMs", performance.now() - t0);
  }, [layout, paintRows, selId, size, ver]);

  const selTile = layout?.tiles.find((t) => t.id === selId);
  const selRow = selId !== null && view ? view.rows[selId] : undefined;
  const readout = (r: NonNullable<typeof selRow>) =>
    `${r.sym} ${r.name} ${fmtPct(r.pct)}${p.sizeShort ? ` ${p.sizeShort} ${fmtBig(r.size)}` : ""}${r.extra ? ` ${r.extra}` : ""} ${r.group.toUpperCase()}`;

  const csvRows = layout && view ? layout.tiles.map((t) => view.rows[t.id]) : [];
  useCsvExport(panelId, () =>
    view && layout
      ? gridCsv(p.csvName, [
          { title: "SYMBOL", width: 8, text: (r) => r.sym },
          { title: "NAME", width: 24, text: (r) => r.name },
          { title: "GROUP", width: 20, text: (r) => r.group },
          { title: p.sizeTitle, width: 10, text: (r) => String(r.size) },
          { title: "%CHG", width: 8, text: (r) => String(r.pct ?? "") },
        ], csvRows)
      : null,
  );

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const st = live.current;
        if (!st.layout) return false;
        const dirs: Record<string, Dir> = { ArrowLeft: "left", h: "left", ArrowRight: "right", l: "right", ArrowUp: "up", k: "up", ArrowDown: "down", j: "down" };
        const dir = dirs[e.key];
        if (dir) {
          const i = st.layout.tiles.findIndex((t) => t.id === st.selId);
          const to = neighbor(st.layout.tiles, Math.max(0, i), dir);
          if (st.layout.tiles[to]) setSelId(st.layout.tiles[to].id);
          return true;
        }
        switch (e.key) {
          case "Enter": {
            const r = st.view && st.selId !== null ? st.view.rows[st.selId] : undefined;
            if (r) navigate(panelId, { fn: "Q", args: [r.open] });
            return true;
          }
          case "z": {
            const t = st.layout.tiles.find((x) => x.id === st.selId);
            if (t) setZoom(st.layout.groupKeys[t.group]);
            return true;
          }
          case "Backspace":
            if (st.zoom) {
              setZoom(null);
              return true;
            }
            return false;
        }
        return false;
      }),
    [panelId, live],
  );

  const pick = (ev: React.MouseEvent) => {
    if (!layout) return;
    const r = ev.currentTarget.getBoundingClientRect();
    const x = ev.clientX - r.left;
    const y = ev.clientY - r.top;
    const t = layout.tiles.find((q) => x >= q.x && x < q.x + q.w && y >= q.y && y < q.y + q.h);
    if (t) setSelId(t.id);
  };

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">IMAP</span> {p.label}{zoom ? ` > ${zoom.toUpperCase()}` : ""}
        {p.rest.length ? ` · ${p.rest.join(" ").toUpperCase()}` : ""}
        {view && ` · ${layout?.tiles.length ?? 0} TILES`}
        <span className="dim"> · SIZE = {p.sizeWord} · COLOUR = {p.colourWord ?? "% CHANGE ON THE DAY"}</span>
        {p.status}
        <span className="dim"> · ARROWS MOVE · ENTER Q · Z ZOOM GROUP · BKSP OUT · E CSV · F5 REFRESH</span>
      </div>
      {p.notes}
      {view && (view.noSize > 0 || view.cut > 0) && (
        <div className="dim">
          {view.noSize > 0 && `${view.noSize} ${p.noSizeText}`}
          {view.noSize > 0 && view.cut > 0 && " · "}
          {view.cut > 0 && `${view.cut} SMALLEST NOT SHOWN (N=${p.limit}; USE N= TO RAISE)`}
        </div>
      )}
      {view && view.rows.length === 0 && <div className="err">NO ROWS MATCH THIS FILTER</div>}
      <div className="imap-legend" aria-hidden="true">
        {BAND_LABELS.map((lab, i) => {
          const band = i - 4;
          return (
            <span key={lab} style={{ background: band === 0 ? "var(--sel)" : `var(${band > 0 ? "--up" : "--down"})`, opacity: band === 0 ? 1 : BAND_ALPHA[Math.abs(band)] + 0.15 }}>
              {lab}
            </span>
          );
        })}
      </div>
      <div ref={wrap} className="imap" onClick={pick}>
        <canvas ref={canvas} data-testid="imap-canvas" style={{ width: size?.w ?? 0, height: size?.h ?? 0 }} />
      </div>
      <div className="sr" role="status" aria-live="polite">
        {selRow ? readout(selRow) : ""}
      </div>
      {selTile && selRow && (
        <div className="line">
          <span className="acc">{selRow.sym}</span> {selRow.name} · {fmtPct(selRow.pct)}{p.sizeShort ? ` · ${p.sizeShort} ${fmtBig(selRow.size)}` : ""}
          {selRow.extra ? ` · ${selRow.extra}` : ""} · {selRow.group.toUpperCase()}
        </div>
      )}
    </div>
  );
}
