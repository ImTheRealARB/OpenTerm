/**
 * GIP: intraday tick chart. Candles are built from the live ticks the backend has seen for the symbol (ring buffer, `GET /api/world/ticks`),
 * then extended from the live tick stream. These are NOT exchange bars: the header says since when and how many ticks.
 * Keys: S bar size (1S 5S 15S 1M), X crosshair, arrows pan, +/- zoom, F5 reload.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChartView, type BarData, type ChartHandle } from "../chart/ChartView";
import { fmtAge } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { ApiError, worldApi, type Envelope, type TickBars } from "../net/api";
import { subscribe } from "../net/socket";
import { symId } from "../state/symbols";
import { getLive, onTicks, SRC_LABEL } from "../state/ticks";
import { replaceView } from "../state/workspace";
import { GIP_SECONDS, gipApiBar, nextGipBar, parseGipArgs } from "./gipArgs";
import { useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";

const LOCAL_TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const clock = (ms: number) => new Date(ms).toLocaleTimeString("en-GB", { hour12: false });

function toBars(symbol: string, d: TickBars): BarData {
  const n = d.t.length;
  return {
    symbol,
    interval: gipApiBar(d.bar_s === 60 ? "1M" : (`${d.bar_s}S` as "1S")),
    tz: LOCAL_TZ,
    t: Float64Array.from(d.t),
    o: Float64Array.from(d.o),
    h: Float64Array.from(d.h),
    l: Float64Array.from(d.l),
    c: Float64Array.from(d.c),
    v: d.v ? Float64Array.from(d.v) : new Float64Array(n),
  };
}

export default function GIP({ panelId, security, args }: FunctionProps) {
  const symbol = security!.symbol;
  const { bar } = useMemo(() => parseGipArgs(args), [args]);
  const [env, setEnv] = useState<Envelope<TickBars> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [crossOn, setCrossOn] = useState(false);
  const [reload, setReload] = useState(0);
  const chart = useRef<ChartHandle>(null);
  const barRef = useLatest(bar);
  const crossRef = useLatest(crossOn);
  const emptyRef = useRef(true);

  const load = useCallback(() => {
    let alive = true;
    worldApi
      .ticks(symbol, gipApiBar(bar))
      .then((e) => {
        if (!alive) return;
        setEnv(e);
        setError(null);
        emptyRef.current = e.data.ticks === 0;
      })
      .catch((e: ApiError) => alive && setError(`${e.message}${e.detail ? ` (${e.detail})` : ""}`));
    return () => {
      alive = false;
    };
  }, [symbol, bar]);

  useEffect(() => {
    setEnv(null);
    return load();
  }, [load, reload]);

  // Live ticks extend the last bar; while the buffer is still empty the first tick triggers one reload, so the chart has data to extend.
  useEffect(() => {
    const unsub = subscribe([symbol]);
    let timer: ReturnType<typeof setTimeout> | null = null;
    const id = symId(symbol);
    const off = onTicks((batch) => {
      if (!batch.has(id)) return;
      const l = getLive(symbol)!;
      if (emptyRef.current) {
        if (!timer) timer = setTimeout(() => setReload((r) => r + 1), 600);
        return;
      }
      chart.current?.live(l.price, l.t, null);
    });
    return () => {
      unsub();
      off();
      if (timer) clearTimeout(timer);
    };
  }, [symbol]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        switch (e.key) {
          case "s":
          case "S":
            replaceView(panelId, (v) => ({ ...v, args: [nextGipBar(barRef.current)] }));
            return true;
          case "x": {
            const on = !crossRef.current;
            chart.current?.crosshair(on);
            setCrossOn(on);
            return true;
          }
          case "ArrowLeft":
            if (crossRef.current) chart.current?.crosshairStep(-1);
            else chart.current?.pan(-10);
            return true;
          case "ArrowRight":
            if (crossRef.current) chart.current?.crosshairStep(1);
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
    [panelId, barRef, crossRef],
  );

  const d = env?.data;
  const data = useMemo(() => (d && d.t.length ? toBars(symbol, d) : null), [d, symbol]);
  const live = getLive(symbol);
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">GIP</span> {symbol} {bar} TICK BARS
        {d && d.ticks > 0 && (
          <span className="dim"> · {d.ticks} TICKS SINCE {clock(d.since_ms!)} · LAST {clock(d.last_ms!)} · {env!.source?.toUpperCase()} · LOCAL TIME ({LOCAL_TZ})</span>
        )}
        {d?.synthetic && <span className="warn"> · SYNTHETIC TEST DATA, NOT A SECURITY</span>}
        {env?.stale && <span className="warn"> · STALE {fmtAge(env.age_s)}</span>}
        {live && <span className="dim"> · LIVE {SRC_LABEL[live.src] ?? ""}</span>}
        {!env && !error && <span className="dim"> · LOADING…</span>}
        {crossOn && <span className="acc"> · CROSSHAIR (←/→, X TO EXIT)</span>}
        <span className="dim"> · S BAR SIZE · X CROSS · ←/→ PAN · +/- ZOOM · F5 RELOAD</span>
      </div>
      {error && <div className="err">{error}. F5 TO RETRY.</div>}
      {d && d.ticks > 0 && (
        <div className="dim">
          CANDLES ARE BUILT FROM TICKS THIS SERVER HAS SEEN (FIRST ONE AT {clock(d.since_ms!)}), NOT FROM THE EXCHANGE: A SESSION STARTED BEFORE THAT IS NOT IN THEM. {GIP_SECONDS[bar]} S BUCKETS, EMPTY BUCKETS LEFT OUT.
          {d.v === null && " NO TICK VOLUME FROM THIS SOURCE."}
        </div>
      )}
      {d && d.ticks === 0 && (
        <div className="warn">NO TICKS SINCE OPEN: NOTHING HAS TRADED ON {symbol} SINCE THIS SERVER STARTED LISTENING (MARKET CLOSED, OR THE FIRST TICK HAS NOT ARRIVED). WAITING…</div>
      )}
      {data && <ChartView ref={chart} data={data} type="CANDLE" log={false} indicators={[]} />}
    </div>
  );
}
