import { useEffect, useMemo, useRef, useState } from "react";
import { registerChartShot } from "../chart/shot";
import { CHART_TYPES, ChartView, toBarData, type BarData, type ChartHandle, type ChartType } from "../chart/ChartView";
import { INDICATORS, type IndicatorName } from "../chart/indicators";
import { fmtAge } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, api } from "../net/api";
import { subscribe } from "../net/socket";
import { getLive, onTicks, SRC_LABEL } from "../state/ticks";
import { replaceView } from "../state/workspace";
import { settingsStore } from "../settings/runtime";
import { useStore } from "../state/store";
import type { FunctionProps } from "./registry";

const RANGES = ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX"];
/** Number keys 1..8 jump to these. */
const KEY_RANGES = ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y", "MAX"];
const INTERVAL_WORDS = new Set(["1MIN", "2MIN", "5MIN", "15MIN", "30MIN", "60MIN", "90MIN", "1H", "D", "1D", "DAILY", "W", "1W", "1WK", "WEEKLY", "MO", "1MO", "MONTHLY"]);
const YAHOO_INTERVALS = new Set(["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1d", "1wk", "1mo"]);

interface Parsed {
  range: string;
  interval?: string;
  compare?: string;
  type: ChartType;
  log: boolean;
  indicators: IndicatorName[];
}

/** GP args: [range] [interval] [VS SYM] [CANDLE|OHLC|LINE|AREA] [LOG] [SMA20 RSI ...]. Order free. */
/** `defaults`: the SETTINGS default range and chart type (Phase 10). */
export function parseGpArgs(args: string[], defaults: { range: string; type: ChartType } = { range: "1Y", type: "CANDLE" }): Parsed {
  const p: Parsed = { range: defaults.range, type: defaults.type, log: false, indicators: [] };
  for (let i = 0; i < args.length; i++) {
    const raw = args[i];
    const a = raw.toUpperCase();
    if (a === "VS" && args[i + 1]) p.compare = args[++i].toUpperCase();
    else if (RANGES.includes(a)) p.range = a;
    else if (YAHOO_INTERVALS.has(raw) || INTERVAL_WORDS.has(a)) p.interval = raw;
    else if ((CHART_TYPES as string[]).includes(a)) p.type = a as ChartType;
    else if (a === "LOG") p.log = true;
    else if (a === "PAT:ICHI") p.indicators.push("ICHIMOKU");
    else if ((INDICATORS as readonly string[]).includes(a)) p.indicators.push(a as IndicatorName);
  }
  return p;
}

function serialize(p: Parsed, defaultType: ChartType = "CANDLE"): string[] {
  return [
    p.range,
    ...(p.interval ? [p.interval] : []),
    ...(p.compare ? ["VS", p.compare] : []),
    ...(p.type !== defaultType ? [p.type] : []),
    ...(p.log ? ["LOG"] : []),
    ...p.indicators,
  ];
}

interface Loaded {
  bars: BarData;
  source: string | null;
  asOf: number;
  stale: boolean;
  fallback: string[];
  compare: { symbol: string; t: Float64Array; c: Float64Array } | null;
  compareError?: string;
}

export default function GP({ panelId, security, args }: FunctionProps) {
  const chartDefaults = useStore(settingsStore, (st) => st.chart);
  const p = useMemo(() => parseGpArgs(args, chartDefaults), [args, chartDefaults]);
  const symbol = security!.symbol;
  const [state, setState] = useState<{ loaded?: Loaded; error?: string; loading: boolean }>({ loading: true });
  const [picker, setPicker] = useState(false);
  const [crossOn, setCrossOn] = useState(false);
  const [reload, setReload] = useState(0);
  const chart = useRef<ChartHandle>(null);
  const pRef = useRef(p);
  pRef.current = p;
  useEffect(() => registerChartShot(panelId, { symbol, range: p.range, shot: () => chart.current?.screenshot() ?? null }), [panelId, symbol, p.range]);

  const update = (fn: (q: Parsed) => Parsed) => replaceView(panelId, (v) => ({ ...v, args: serialize(fn(pRef.current), chartDefaults.type) }));

  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    const main = api.history(symbol, p.range, p.interval);
    const cmp = p.compare ? api.history(p.compare, p.range, p.interval).catch((e: ApiError) => e) : Promise.resolve(null);
    Promise.all([main, cmp])
      .then(([env, c]) => {
        if (!alive) return;
        const compare = c && !(c instanceof ApiError) ? { symbol: c.data.symbol, ...pick(toBarData(c.data)) } : null;
        setState({
          loading: false,
          loaded: {
            bars: toBarData(env.data), source: env.source, asOf: env.as_of, stale: env.stale, fallback: env.fallback_from, compare,
            compareError: c instanceof ApiError ? `${p.compare}: ${c.message}` : undefined,
          },
        });
      })
      .catch((e: ApiError) => alive && setState({ loading: false, error: e.message }));
    return () => {
      alive = false;
    };
  }, [symbol, p.range, p.interval, p.compare, reload]);

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

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const k = e.key;
        if (picker) {
          const n = Number(k);
          if (n >= 1 && n <= INDICATORS.length) {
            const name = INDICATORS[n - 1];
            update((q) => ({ ...q, indicators: q.indicators.includes(name) ? q.indicators.filter((x) => x !== name) : [...q.indicators, name] }));
            return true;
          }
          if (k === "Escape" || k === "i") {
            setPicker(false);
            return true;
          }
          return true; // picker is modal inside the panel
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
    [panelId, picker, crossOn],
  );

  const L = state.loaded;
  const live = L ? getLive(L.bars.symbol) : undefined;
  return (
    <div className="fn" style={{ position: "relative" }}>
      <div className="line">
        <span className="acc">{L?.bars.symbol ?? symbol}</span> {p.range} {L?.bars.interval ?? p.interval ?? ""} {p.compare ? `VS ${p.compare} (%)` : p.type}
        {p.log && !p.compare && " LOG"} {p.indicators.join(" ")}
        {L && (
          <span className="dim">
            {" · "}
            {L.source === "local" ? "LOCAL DATA (IMPORTED BY YOU)" : L.source?.toUpperCase()} AS OF {fmtAge(Math.max(0, Date.now() / 1000 - L.asOf))} AGO
            {live && ` · LIVE ${SRC_LABEL[live.src] ?? ""}`}
          </span>
        )}
        {L?.stale && <span className="warn"> · STALE</span>}
        {L?.fallback.length ? <span className="warn"> · {L.fallback.join(",").toUpperCase()} DOWN, VIA FALLBACK</span> : null}
        {L?.compareError && <span className="err"> · {L.compareError}</span>}
        {state.loading && <span className="dim"> · LOADING…</span>}
        {crossOn && <span className="acc"> · CROSSHAIR (←/→, X TO EXIT)</span>}
        <span className="dim"> · 1-8 RANGE · C TYPE · I IND · L LOG · ←/→ PAN · +/- ZOOM · X CROSS · CHARTS: TRADINGVIEW LIGHTWEIGHT CHARTS</span>
      </div>
      {state.error && !L && (
        <div className="err">
          {state.error} ({symbol} {p.range}). F5 TO RETRY.
        </div>
      )}
      {!L && !state.error && <div className="dim">LOADING {symbol} {p.range}…</div>}
      {L && <ChartView ref={chart} data={L.bars} compare={L.compare} type={p.type} log={p.log} indicators={p.indicators} />}
      {picker && (
        <div className="picker">
          <div className="acc">INDICATORS (NUMBER TOGGLES, ESC CLOSES)</div>
          {INDICATORS.map((name, i) => (
            <div key={name}>
              {i + 1} {p.indicators.includes(name) ? "[X]" : "[ ]"} {name}
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
