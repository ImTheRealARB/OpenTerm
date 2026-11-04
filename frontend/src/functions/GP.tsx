import { useEffect, useMemo, useRef, useState } from "react";
import { registerChartShot } from "../chart/shot";
import { CHART_TYPES, INTERVAL_S, ChartView, toBarData, type BarData, type ChartHandle, type ChartMarkerEvent } from "../chart/ChartView";
import { createDrawSaver } from "../chart/drawSave";
import { MAX_DRAWINGS, NEEDED, KIND_NAME, cycleSelection, newId, parseDrawings, snapDay, type DPoint, type DrawKind, type Drawing } from "../chart/drawings";
import { PanelNote } from "../components/PanelNote";
import { isKeyRequired, KeyRequiredLine } from "./KeyRequiredLine";
import { INDICATORS } from "../chart/indicators";
import { fmtAge } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api, worldApi, type ChartEvents, type Envelope } from "../net/api";
import { subscribe } from "../net/socket";
import { getLive, onTicks, SRC_LABEL } from "../state/ticks";
import { navigate, replaceView } from "../state/workspace";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { KEY_RANGES, parseGpArgs, serializeGp, type GpParsed } from "./gpArgs";
import { useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";

export { parseGpArgs };

/** Indicator picker keys: 1-9 then letters (I is left out: it closes the picker). */
const PICK_KEYS = "123456789ABCDEFGHJKLMNP";
const ANCHOR_NAME = { C: "CLOSE", H: "HIGH", L: "LOW", O: "OPEN" } as const;
const ANCHOR_NEXT = { C: "H", H: "L", L: "O", O: "C" } as const;

interface Loaded {
  bars: BarData;
  source: string | null;
  asOf: number;
  stale: boolean;
  fallback: string[];
  compares: { symbol: string; t: Float64Array; c: Float64Array }[];
  compareErrors: string[];
}

interface Mode {
  kind: DrawKind;
  pts: DPoint[];
  anchor: "C" | "H" | "L" | "O";
}

export default function GP({ panelId, security, args }: FunctionProps) {
  const chartDefaults = useStore(settingsStore, (st) => st.chart);
  const p = useMemo(() => parseGpArgs(args, chartDefaults), [args, chartDefaults]);
  const symbol = security!.symbol;
  const [state, setState] = useState<{ loaded?: Loaded; error?: string; keyError?: ApiError; loading: boolean }>({ loading: true });
  const [picker, setPicker] = useState(false);
  const [crossOn, setCrossOn] = useState(false);
  const [reload, setReload] = useState(0);
  const chart = useRef<ChartHandle>(null);
  const pRef = useRef(p);
  pRef.current = p;
  useEffect(() => registerChartShot(panelId, { symbol, range: p.range, shot: () => chart.current?.screenshot() ?? null }), [panelId, symbol, p.range]);

  const update = (fn: (q: GpParsed) => GpParsed) => replaceView(panelId, (v) => ({ ...v, args: serializeGp(fn(pRef.current), chartDefaults.type) }));

  // --- bars (and compare symbols) ---
  const compareKey = p.compare.join(",");
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    const main = api.history(symbol, p.range, p.interval);
    const cmp = Promise.all(p.compare.map((c) => api.history(c, p.range, p.interval).catch((e: ApiError) => e)));
    Promise.all([main, cmp])
      .then(([env, cs]) => {
        if (!alive) return;
        const compares: Loaded["compares"] = [];
        const compareErrors: string[] = [];
        cs.forEach((c, i) => {
          if (c instanceof ApiError) compareErrors.push(`${p.compare[i]}: ${c.message}`);
          else compares.push({ symbol: c.data.symbol, ...pick(toBarData(c.data)) });
        });
        setState({
          loading: false,
          loaded: { bars: toBarData(env.data), source: env.source, asOf: env.as_of, stale: env.stale, fallback: env.fallback_from, compares, compareErrors },
        });
      })
      .catch((e: ApiError) => alive && setState({ loading: false, error: e.message, keyError: isKeyRequired(e) ? e : undefined }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, p.range, p.interval, compareKey, reload]);

  // Live: extend the last bar from ticks.
  const resolved = state.loaded?.bars.symbol;
  useEffect(() => {
    if (!resolved) return;
    const unsub = subscribe([resolved]);
    const off = onTicks((changed) => {
      if (!changed.has(resolved)) return;
      const l = getLive(resolved)!;
      chart.current?.live(l.price, l.t, l.volume);
    });
    return () => {
      unsub();
      off();
    };
  }, [resolved, state.loaded]);

  // --- drawings: stored per symbol on the server, saved 0.4 s after the last change ---
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode | null>(null);
  const [drawNote, setDrawNote] = useState<string | null>(null);
  // One saver per panel: it saves to the symbol the loaded list belongs to, so a symbol switch in place cannot mis-address a save.
  const saver = useMemo(() => createDrawSaver((sym, list) => worldApi.saveDrawings(sym, list), setDrawNote), []);
  useEffect(() => {
    let alive = true;
    saver.reset();
    setDrawings([]);
    setSelected(null);
    setMode(null);
    worldApi
      .drawings(symbol)
      .then((r) => {
        if (!alive) return;
        setDrawings(parseDrawings(r.drawings));
        saver.loaded(symbol);
        setDrawNote(null);
      })
      .catch((e: ApiError) => alive && setDrawNote(`DRAWINGS NOT LOADED: ${e.message}`));
    return () => {
      alive = false;
      saver.flush();
    };
  }, [symbol, saver]);
  const commit = (next: Drawing[]) => {
    setDrawings(next);
    saver.change(next);
  };

  // --- event markers (EVT) ---
  const [events, setEvents] = useState<{ env?: Envelope<ChartEvents>; error?: string } | null>(null);
  useEffect(() => {
    if (!p.evt) {
      setEvents(null);
      return;
    }
    let alive = true;
    worldApi
      .events(symbol, reload > 0)
      .then((env) => alive && setEvents({ env }))
      .catch((e: ApiError) => alive && setEvents({ error: `${e.message}${e.detail ? ` (${e.detail})` : ""}` }));
    return () => {
      alive = false;
    };
  }, [symbol, p.evt, reload]);

  const L = state.loaded;
  const markers = useMemo<ChartMarkerEvent[] | undefined>(() => {
    if (!L || !p.evt || !events?.env) return undefined;
    const iv = INTERVAL_S[L.bars.interval] ?? 86400;
    return events.env.data.events.flatMap((e) => {
      const t = snapDay(e.date, L.bars.t, iv);
      return t === null ? [] : [{ t, kind: e.kind, detail: `${e.date} ${e.detail}` }];
    });
  }, [L, p.evt, events]);

  const drawState = useMemo(() => ({ drawings, selected, pending: mode }), [drawings, selected, mode]);
  const live = useLatest({ drawings, selected, mode, bars: L?.bars });

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const k = e.key;
        if (picker) {
          const idx = PICK_KEYS.indexOf(k.toUpperCase());
          if (k.length === 1 && idx >= 0 && idx < INDICATORS.length) {
            const name = INDICATORS[idx];
            update((q) => ({ ...q, indicators: q.indicators.includes(name) ? q.indicators.filter((x) => x !== name) : [...q.indicators, name] }));
            return true;
          }
          if (k === "Escape" || k === "i") {
            setPicker(false);
            return true;
          }
          return true; // picker is modal inside the panel
        }
        const st = live.current;
        const plain = !e.ctrlKey && !e.altKey && !e.metaKey;
        if (st.mode && plain) {
          if (k === "Escape") {
            setMode(null);
            return true;
          }
          if (k === "p") {
            setMode({ ...st.mode, anchor: ANCHOR_NEXT[st.mode.anchor] });
            return true;
          }
          if (k === "Enter") {
            const b = st.bars;
            if (!b || !chart.current) return true;
            const i = chart.current.crosshairIndex();
            const px = st.mode.anchor === "H" ? b.h[i] : st.mode.anchor === "L" ? b.l[i] : st.mode.anchor === "O" ? b.o[i] : b.c[i];
            if (!Number.isFinite(px) || !Number.isFinite(b.t[i])) return true;
            const pts = [...st.mode.pts, { t: b.t[i], p: px }];
            if (pts.length < NEEDED[st.mode.kind]) {
              setMode({ ...st.mode, pts });
              return true;
            }
            if (st.drawings.length >= MAX_DRAWINGS) {
              setDrawNote(`AT MOST ${MAX_DRAWINGS} DRAWINGS PER SYMBOL: DELETE ONE FIRST`);
              setMode(null);
              return true;
            }
            const id = newId(st.drawings);
            commit([...st.drawings, { id, kind: st.mode.kind, pts }]);
            setSelected(id);
            setMode(null);
            return true;
          }
        }
        if (plain && !st.mode) {
          const start = (kind: DrawKind) => {
            if (!st.bars) return true;
            if (!crossOn) {
              chart.current?.crosshair(true);
              setCrossOn(true);
            }
            setSelected(null);
            setMode({ kind, pts: [], anchor: "C" });
            return true;
          };
          if (k === "t") return start("TREND");
          if (k === "h") return start("HLINE");
          if (k === "b") return start("FIB");
          if (k === "]" || k === "[") {
            setSelected(cycleSelection(st.drawings, st.selected, k === "]" ? 1 : -1));
            return true;
          }
          if ((k === "Delete" || k === "d") && st.selected) {
            commit(st.drawings.filter((d) => d.id !== st.selected));
            setSelected(null);
            return true;
          }
          if (k === "Escape" && st.selected) {
            setSelected(null);
            return true;
          }
        }
        const n = Number(k);
        if (n >= 1 && n <= 8) {
          update((q) => ({ ...q, range: KEY_RANGES[n - 1], interval: undefined }));
          return true;
        }
        switch (k) {
          case "c":
            update((q) => ({ ...q, type: CHART_TYPES[(CHART_TYPES.indexOf(q.type) + 1) % CHART_TYPES.length] }));
            return true;
          case "l":
            update((q) => ({ ...q, log: !q.log }));
            return true;
          case "i":
            setPicker(true);
            return true;
          case "x": {
            const on = !crossOn;
            chart.current?.crosshair(on);
            setCrossOn(on);
            return true;
          }
          case "ArrowLeft":
            if (crossOn) chart.current?.crosshairStep(-1);
            else chart.current?.pan(-10);
            return true;
          case "ArrowRight":
            if (crossOn) chart.current?.crosshairStep(1);
            else chart.current?.pan(10);
            return true;
          case "+":
          case "=":
            chart.current?.zoom(0.8);
            return true;
          case "-":
            chart.current?.zoom(1.25);
            return true;
          case "F5":
            setReload((r) => r + 1);
            return true;
        }
        return false;
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [panelId, picker, crossOn],
  );

  const liveQ = L ? getLive(L.bars.symbol) : undefined;
  const sel = drawings.find((d) => d.id === selected);
  const overlayCompare = !p.pane && L?.compares.length ? L.compares[0] : null;
  const shownEvents = markers?.length ?? 0;
  return (
    <div className="fn gp" style={{ position: "relative" }}>
      <div className="line">
        <span className="acc">{L?.bars.symbol ?? symbol}</span> {p.range} {L?.bars.interval ?? p.interval ?? ""}{" "}
        {p.compare.length ? `VS ${p.compare.join(" ")} ${p.pane ? "(PANES)" : "(%)"}` : p.type}
        {p.log && !overlayCompare && " LOG"} {p.indicators.join(" ")}
        {L && (
          <span className="dim">
            {" · "}
            {L.source === "local" ? "LOCAL DATA (IMPORTED BY YOU)" : L.source?.toUpperCase()} AS OF {fmtAge(Math.max(0, Date.now() / 1000 - L.asOf))} AGO
            {liveQ && ` · LIVE ${SRC_LABEL[liveQ.src] ?? ""}`}
          </span>
        )}
        {L?.stale && <span className="warn"> · STALE</span>}
        {L?.fallback.length ? <span className="warn"> · {L.fallback.join(",").toUpperCase()} DOWN, VIA FALLBACK</span> : null}
        {L?.compareErrors.map((m) => (
          <span className="err" key={m}> · {m}</span>
        ))}
        {state.loading && <span className="dim"> · LOADING…</span>}
        {crossOn && !mode && <span className="acc"> · CROSSHAIR (←/→, X TO EXIT)</span>}
        {mode && (
          <span className="acc">
            {" · "}DRAW {KIND_NAME[mode.kind]}: ANCHOR {mode.pts.length + 1}/{NEEDED[mode.kind]} AT {ANCHOR_NAME[mode.anchor]} · ←/→ MOVE · P PRICE · ENTER PLACES · ESC CANCELS
          </span>
        )}
        {!mode && sel && (
          <span className="acc"> · {KIND_NAME[sel.kind]} {sel.id} SELECTED · [ ] CYCLE · D REMOVES</span>
        )}
        {drawNote && <span className="err"> · {drawNote}</span>}
        <span className="dim"> · 1-8 RANGE · C TYPE · I IND · L LOG · ←/→ PAN · +/- ZOOM · X CROSS · T/H/B DRAW · CHARTS: TRADINGVIEW LIGHTWEIGHT CHARTS</span>
      </div>
      {p.evt && (
        <div className="line dim">
          {events?.error ? <span className="err">EVT: {events.error}</span> : !events ? "EVT: LOADING…" : (
            <>
              EVT E=EARNINGS (LAST 4 REPORTED) D=EX-DIVIDEND S=SPLIT · {shownEvents} IN VIEW OF {events.env!.data.events.length} · {events.env!.source?.toUpperCase()}
              {events.env!.data.missing.length ? <span className="warn"> · MISSING {events.env!.data.missing.join(", ")}</span> : null}
            </>
          )}
        </div>
      )}
      {overlayCompare && drawings.length > 0 && <div className="warn">DRAWINGS HIDDEN WHILE A % OVERLAY (VS) IS ON: USE PANE TO KEEP THEM</div>}
      {p.compare.length > 1 && !p.pane && <div className="warn">VS OVERLAYS ONLY {p.compare[0]}; ADD PANE TO SHOW ALL {p.compare.length}</div>}
      {/* Same look as every other panel (components/PanelNote): the error keeps its text, the hint says what to do next. */}
      {state.keyError && !L && <KeyRequiredLine error={state.keyError} />}
      {state.error && !state.keyError && !L && (
        <PanelNote
          kind="error"
          hint="F5 TO RETRY."
          // GUI wording: a symbol the user picked is valid, so never blame the spelling here; say what is actually wrong.
          plain={
            /NO DATA|NOT FOUND/i.test(state.error)
              ? `No chart data came back for ${symbol} over ${p.range}. The name is fine: the data source has nothing for it right now (in sample-data mode that can be a gap in the recordings). Retry, try another range, or chart a different stock.`
              : undefined
          }
          actions={symbol !== "AAPL" ? [{ label: "Try AAPL", onClick: () => navigate(panelId, { fn: "GP", security: { symbol: "AAPL" }, args: [] }) }] : []}
          onRetry={() => setReload((n) => n + 1)}
        >
          {state.error} ({symbol} {p.range}).
        </PanelNote>
      )}
      {!L && !state.error && <PanelNote kind="loading">LOADING {symbol} {p.range}…</PanelNote>}
      {L && (
        <ChartView
          ref={chart}
          data={L.bars}
          compare={overlayCompare}
          comparePanes={p.pane ? L.compares : undefined}
          type={p.type}
          log={p.log}
          indicators={p.indicators}
          draw={drawState}
          events={markers}
          onPick={(id) => setSelected(id)}
        />
      )}
      {picker && (
        <div className="picker">
          <div className="acc">INDICATORS (KEY TOGGLES, ESC CLOSES)</div>
          {INDICATORS.map((name, i) => (
            <div key={name}>
              {PICK_KEYS[i]} {p.indicators.includes(name) ? "[X]" : "[ ]"} {name}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function pick(b: BarData) {
  return { t: b.t, c: b.c };
}
