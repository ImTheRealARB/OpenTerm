/**
 * IMAP: heat map of the EQS screener universe. Tiles are sized by market cap and coloured by today's % change; groups are sectors,
 * industries or countries. Layout and colour bands are pure (treemap.ts); painting is one canvas pass (imapPaint.ts).
 * Keys: arrows / H J K L move between tiles, Enter opens Q, Z zooms into the group, Backspace zooms out, E exports CSV, F5 refreshes.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fmtAge, fmtBig, fmtPct } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { ApiError } from "../net/core";
import { marketApi } from "../net/marketApi";
import type { Envelope, ScreenerPayload } from "../net/types";
import { gauges } from "../perf/metrics";
import { displayVersion } from "../settings/runtime";
import { useStore } from "../state/store";
import { navigate } from "../state/workspace";
import { parseFilter } from "./eqsFilter";
import { buildImap, parseImapArgs } from "./imapData";
import { BAND_ALPHA, BAND_LABELS, paintTreemap, type PaintColors } from "./imapPaint";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import { neighbor, treemap, type Dir } from "./treemap";

function themeColors(): PaintColors {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string) => cs.getPropertyValue(n).trim();
  return { bg: v("--bg"), fg: v("--fg"), dim: v("--fg-dim"), up: v("--up"), down: v("--down"), sel: v("--sel"), line: v("--line"), font: v("--font") };
}

export default function IMAP({ panelId, args }: FunctionProps) {
  const [env, setEnv] = useState<Envelope<ScreenerPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [selId, setSelId] = useState<number | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const ver = useStore(displayVersion, (v) => v);
  const colors = useRef<PaintColors | null>(null);

  const load = useCallback((fresh: boolean) => {
    setLoading(true);
    return marketApi
      .screener(fresh)
      .then((e) => {
        setEnv(e);
        setError(null);
      })
      .catch((e: ApiError) => setError(e))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    void load(false);
  }, [load]);

  const opts = useMemo(() => parseImapArgs(args), [args]);
  const prepared = useMemo(() => (env ? buildImap(env.data, parseFilter(opts.rest), opts) : null), [env, opts]);
  useEffect(() => {
    setZoom(null);
  }, [args]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: Math.floor(el.clientWidth), h: Math.floor(el.clientHeight) }));
    ro.observe(el);
    setSize({ w: Math.floor(el.clientWidth), h: Math.floor(el.clientHeight) });
    return () => ro.disconnect();
  }, []);

  const layout = useMemo(() => {
    if (!prepared || !size || size.w < 20 || size.h < 20) return null;
    const groups = zoom ? prepared.groups.filter((g) => g.key === zoom) : prepared.groups;
    const t0 = performance.now();
    const l = treemap(groups, size.w, size.h, { header: 14, pad: 1 });
    gauges.set("imap.layoutMs", performance.now() - t0);
    gauges.set("imap.tiles", l.tiles.length);
    return { ...l, groupKeys: groups.map((g) => g.key) };
  }, [prepared, size, zoom]);

  const paintRows = useMemo(() => (prepared ? prepared.rows.map((r) => ({ sym: r[0], pct: r[4] })) : []), [prepared]);
  const live = useLatest({ layout, prepared, selId, zoom });

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
  const selRow = selId !== null && prepared ? prepared.rows[selId] : undefined;
  const groupOf = (id: number | null) => (layout && id !== null ? layout.groupKeys[layout.tiles.find((t) => t.id === id)?.group ?? 0] : undefined);

  const csvRows = layout && prepared ? layout.tiles.map((t) => prepared.rows[t.id]) : [];
  useCsvExport(panelId, () =>
    env && prepared && layout
      ? gridCsv(`IMAP_${opts.by}_${args.join("_") || "ALL"}`, [
          { title: "SYMBOL", width: 8, text: (r) => r[0] },
          { title: "NAME", width: 24, text: (r) => r[1] },
          { title: "GROUP", width: 20, text: (r) => groupOf(prepared.rows.indexOf(r)) ?? "" },
          { title: "MKT CAP", width: 10, text: (r) => String(r[6] ?? "") },
          { title: "%CHG", width: 8, text: (r) => String(r[4] ?? "") },
        ], csvRows)
      : null,
  );

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
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
            const r = st.prepared && st.selId !== null ? st.prepared.rows[st.selId] : undefined;
            if (r) navigate(panelId, { fn: "Q", args: [r[0]] });
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

  const u = env?.data;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">IMAP</span> {opts.by}{zoom ? ` > ${zoom.toUpperCase()}` : ""}
        {opts.rest.length ? ` · ${opts.rest.join(" ").toUpperCase()}` : ""}
        {prepared && ` · ${layout?.tiles.length ?? 0} TILES`}
        <span className="dim"> · SIZE = MARKET CAP · COLOUR = % CHANGE ON THE DAY</span>
        {u && <span className="dim"> · {u.source.toUpperCase()}{u.as_of_text ? ` · ${u.as_of_text.toUpperCase()}` : ""}</span>}
        {env && <span className={env.stale ? "warn" : "dim"}> · {env.stale ? "STALE " : "AGE "}{fmtAge(env.age_s)}</span>}
        {loading && <span className="dim"> · LOADING…</span>}
        <span className="dim"> · ARROWS MOVE · ENTER Q · Z ZOOM GROUP · BKSP OUT · E CSV · F5 REFRESH</span>
      </div>
      {error && <div className="err">{error.message}{error.detail ? ` (${error.detail})` : ""}. F5 TO RETRY.</div>}
      {prepared && (prepared.noCap > 0 || prepared.cut > 0) && (
        <div className="dim">
          {prepared.noCap > 0 && `${prepared.noCap} ROWS WITHOUT A MARKET CAP HAVE NO TILE`}
          {prepared.noCap > 0 && prepared.cut > 0 && " · "}
          {prepared.cut > 0 && `${prepared.cut} SMALLEST NOT SHOWN (N=${opts.limit}; USE N= TO RAISE)`}
        </div>
      )}
      {prepared && prepared.rows.length === 0 && <div className="err">NO ROWS MATCH THIS FILTER</div>}
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
        {selRow ? `${selRow[0]} ${selRow[1]} ${fmtPct(selRow[4])} MCAP ${fmtBig(selRow[6])} ${(groupOf(selId) ?? "").toUpperCase()}` : ""}
      </div>
      {selTile && selRow && (
        <div className="line">
          <span className="acc">{selRow[0]}</span> {selRow[1]} · {fmtPct(selRow[4])} · MCAP {fmtBig(selRow[6])} · {(groupOf(selId) ?? "").toUpperCase()}
        </div>
      )}
    </div>
  );
}
