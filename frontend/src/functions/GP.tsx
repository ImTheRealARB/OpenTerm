import { useEffect, useMemo, useRef, useState } from "react";
import { registerChartShot } from "../chart/shot";
import { CHART_TYPES, INTERVAL_S, ChartView, toBarData, type BarData, type ChartHandle, type ChartMarkerEvent, type CustomItem } from "../chart/ChartView";
import { onIndicatorRequest, setChartIndicators, type IndicatorRequest } from "../chart/indicatorBus";
import { alertDirection, fmtAlertPrice, roundAlertPrice } from "../chart/alertPrice";
import { createDrawSaver } from "../chart/drawSave";
import { MAX_DRAWINGS, NEEDED, KIND_NAME, cycleSelection, newId, parseDrawings, snapDay, type DPoint, type DrawKind, type Drawing } from "../chart/drawings";
import { PanelNote } from "../components/PanelNote";
import { isKeyRequired, KeyRequiredLine } from "./KeyRequiredLine";
import { INDICATORS } from "../chart/indicators";
import { fmtAge } from "../format";
import { alerts as alertStore } from "../command/alerts";
import { createPriceAlert } from "../command/priceAlert";
import { fail } from "../command/status";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api, worldApi, type ChartEvents, type Envelope } from "../net/api";
import { subscribe } from "../net/socket";
import { symId } from "../state/symbols";
import { getLive, onTicks, SRC_LABEL } from "../state/ticks";
import { currentView, navigate, replaceView, workspace } from "../state/workspace";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import { KEY_RANGES, MAX_CUSTOM, depthLimitFromError, formulaInd, libraryInd, limitText, longestRangeWithin, parseGpArgs, serializeGp, type GpParsed } from "./gpArgs";
import { fallbackText } from "./fallbackText";
import { useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";

export { parseGpArgs };

/** Indicator picker keys: 1-9 then letters (I is left out: it closes the picker). */
const PICK_KEYS = "123456789ABCDEFGHJKLMNPQR"; // one key per INDICATORS entry, in order (I and O are skipped: they look like 1 and 0)
const ANCHOR_NAME = { C: "CLOSE", H: "HIGH", L: "LOW", O: "OPEN" } as const;
const ANCHOR_NEXT = { C: "H", H: "L", L: "O", O: "C" } as const;

interface Loaded {
  bars: BarData;
  source: string | null;
  asOf: number;
  stale: boolean;
  fallback: string[];
  fallbackNotes?: Record<string, string>;
  compares: { symbol: string; t: Float64Array; c: Float64Array }[];
  compareErrors: string[];
}

/** The GP panel that answers IND requests: the focused GP, else the GP focused last. */
const gpLast: { id: number | null } = { id: null };

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

  // `pRef` moves on at once, so several changes in one tick (a preset adding 20 indicators) build on each other.
  const update = (fn: (q: GpParsed) => GpParsed) => {
    const next = fn(pRef.current);
    pRef.current = next;
    replaceView(panelId, (v) => ({ ...v, args: serializeGp(next, chartDefaults.type) }));
  };

  // The chosen candle length does not reach back that far (e.g. 5 min + 1Y on Yahoo). The server says so ("... ONLY AVAILABLE FOR THE
  // LAST 60 DAYS") and it knows which source answered, so the error text is the authority; this lets the note offer fixes.
  const depthDays = state.error ? depthLimitFromError(state.error) : null;
  const clash = depthDays !== null;

  // --- library indicators and formulas (IND): one GP answers, the same add/remove path as the toolbar toggles ---
  const [customErrors, setCustomErrors] = useState<Record<string, string>>({});
  const custom = useMemo<CustomItem[]>(() => p.custom.map((c) => ({ key: c.key, label: c.label, id: c.id, params: c.params, formula: c.formula })), [p.custom]);
  const customKeys = p.custom.map((c) => c.key);
  const customKeyStr = customKeys.join("\n");
  const isAnswering = () => {
    const f = workspace.get().focus;
    const fv = workspace.get().panels[f];
    return f === panelId || (gpLast.id === panelId && (!fv || currentView(fv).fn !== "GP"));
  };
  useEffect(() => {
    const track = () => {
      // A GP mounted while nothing else claims the role (reloaded layout, remount after a split) takes it.
      if (workspace.get().focus === panelId || gpLast.id === null) gpLast.id = panelId;
      if (isAnswering()) setChartIndicators(pRef.current.custom.map((c) => c.key));
    };
    track();
    const off = workspace.subscribe(track);
    const offReq = onIndicatorRequest((req: IndicatorRequest) => {
      if (!isAnswering()) return false;
      const ind = "formula" in req ? formulaInd(req.formula) : libraryInd(req.id, req.params ?? []);
      const has = pRef.current.custom.some((c) => c.key === ind.key);
      if (has && req.op !== "toggle") return true;
      if (!has && pRef.current.custom.length >= MAX_CUSTOM) {
        fail(`AT MOST ${MAX_CUSTOM} CUSTOM INDICATORS ON ONE CHART`);
        return true;
      }
      update((q) => ({ ...q, custom: has ? q.custom.filter((c) => c.key !== ind.key) : [...q.custom, ind] }));
      return true;
    });
    return () => {
      off();
      offReq();
      if (gpLast.id === panelId) {
        gpLast.id = null;
        setChartIndicators([]);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panelId]);
  useEffect(() => {
    if (isAnswering()) setChartIndicators(customKeyStr ? customKeyStr.split("\n") : []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customKeyStr]);

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
          loaded: { bars: toBarData(env.data), source: env.source, asOf: env.as_of, stale: env.stale, fallback: env.fallback_from, fallbackNotes: env.fallback_notes, compares, compareErrors },
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
    const id = symId(resolved);
    const off = onTicks((batch) => {
      if (!batch.has(id)) return;
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
  // --- alert from the chart: key A (crosshair or last price), Shift+A or the toolbar button arms one click, Alt+click always ---
  const [armed, setArmed] = useState(false);
  const allAlerts = useStore(alertStore, (a) => a);
  const alertKey = (allAlerts ?? [])
    .filter((a) => a.status === "active" && a.unit === "price" && a.symbol === (L?.bars.symbol ?? symbol))
    .map((a) => a.value)
    .sort((a, b) => a - b)
    .join(",");
  const alertLevels = useMemo(() => (alertKey ? alertKey.split(",").map(Number) : []), [alertKey]);
  const placeAlert = (raw: number | null) => {
    const sym = L?.bars.symbol ?? symbol;
    const last = chart.current?.lastPrice() ?? null;
    if (raw === null || last === null || !Number.isFinite(raw)) return fail("NO PRICE YET");
    const price = roundAlertPrice(raw);
    if (price === null) return fail("ALERT PRICE MUST BE ABOVE 0");
    void createPriceAlert(sym, alertDirection(price, last), fmtAlertPrice(price));
    return true;
  };
  const overlayOn = !p.pane && !!L?.compares.length;
  useEffect(() => setArmed(false), [symbol, panelId]);
  const live = useLatest({ drawings, selected, mode, bars: L?.bars, armed, placeAlert, overlayOn });

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
        if (st.armed && k === "Escape") {
          setArmed(false);
          return true;
        }
        if (plain && !st.mode) {
          if (k === "a") {
            st.placeAlert(chart.current?.alertPrice() ?? null);
            return true;
          }
          if (k === "A") {
            if (!st.bars) return fail("NO PRICE YET");
            if (st.overlayOn) return fail("ALERT FROM THE CHART NEEDS THE PLAIN PRICE CHART: REMOVE VS FIRST");
            setArmed(!st.armed);
            return true;
          }
        }
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
          // Change only the range; keep the candle length the user picked (it used to snap back to Auto here).
          update((q) => ({ ...q, range: KEY_RANGES[n - 1] }));
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
        {p.log && !overlayCompare && " LOG"} {p.indicators.join(" ")} {p.custom.map((c) => c.label).join(" ")}
        {L && (
          <span className="dim">
            {" · "}
            {L.source === "local" ? "LOCAL DATA (IMPORTED BY YOU)" : L.source?.toUpperCase()} AS OF {fmtAge(Math.max(0, Date.now() / 1000 - L.asOf))} AGO
            {liveQ && ` · LIVE ${SRC_LABEL[liveQ.src] ?? ""}`}
          </span>
        )}
        {L?.stale && <span className="warn"> · STALE</span>}
        {L?.fallback.length ? <span className="warn"> · {fallbackText(L.fallback, L.fallbackNotes)}</span> : null}
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
        {armed && <span className="acc"> · CLICK THE CHART TO SET AN ALERT, ESC TO CANCEL</span>}
        {drawNote && <span className="err"> · {drawNote}</span>}
        {Object.values(customErrors).map((m) => (
          <span className="err" key={m} data-testid="gp-custom-err"> · {m}</span>
        ))}
        <span className="dim legend"> · 1-8 RANGE · C TYPE · I IND · L LOG · ←/→ PAN · +/- ZOOM · X CROSS · T/H/B DRAW · A ALERT (SHIFT+A OR ALT+CLICK: AT A CLICKED PRICE) · CHARTS: TRADINGVIEW LIGHTWEIGHT CHARTS</span>
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
          hint={clash ? "PICK A LONGER CANDLE (AUTO) OR A SHORTER RANGE." : "F5 TO RETRY."}
          // GUI wording: a symbol the user picked is valid, so never blame the spelling here; say what is actually wrong.
          plain={
            clash
              ? `The data source only has ${p.interval ?? "these"} candles ${limitText(depthDays!)} back, and ${p.range} is longer than that. Your candle length is kept; pick one of the fixes below.`
              : /NO DATA|NOT FOUND/i.test(state.error)
                ? `No chart data came back for ${symbol} over ${p.range}. The name is fine: the data source has nothing for it right now (in sample-data mode that can be a gap in the recordings). Retry, try another range, or chart a different stock.`
                : undefined
          }
          actions={[
            ...(clash
              ? [
                  { label: "Use Auto candles", onClick: () => update((q) => ({ ...q, interval: undefined })) },
                  ...(longestRangeWithin(depthDays!) ? [{ label: `Show ${longestRangeWithin(depthDays!)} instead`, onClick: () => update((q) => ({ ...q, range: longestRangeWithin(depthDays!)! })) }] : []),
                ]
              : []),
            ...(symbol !== "AAPL" ? [{ label: "Try AAPL", onClick: () => navigate(panelId, { fn: "GP", security: { symbol: "AAPL" }, args: [] }) }] : []),
          ]}
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
          custom={custom}
          onCustomErrors={setCustomErrors}
          draw={drawState}
          events={markers}
          onPick={(id) => setSelected(id)}
          alertLevels={alertLevels}
          pickArmed={armed}
          onPickPrice={(px) => {
            setArmed(false);
            live.current.placeAlert(px);
          }}
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
