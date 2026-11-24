/**
 * TPO (Phase 23): market profile. `TPO [SYM] [DAYS] [BRACKET=30]`: for each of the last DAYS trading days (default 5, at
 * most 20), every BRACKET minutes (default 30) gets a letter, written on each price row that bracket traded at. The maths is
 * `tpoMath.ts` (unit tested); this file fetches 5-minute bars, splits them into exchange-local days and draws a text grid.
 *
 * Built from bar high-low per bracket, the standard construction: exact for the 5-minute bars it uses (the line says so).
 * Yahoo keeps 5-minute bars for about 60 days, so DAYS is capped at 20 (the 1-month range).
 */
import { useMemo } from "react";
import { fmtNum } from "../format";
import { marketApi } from "../net/marketApi";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { usePanelRefresh } from "./panelRefresh";
import type { FunctionProps } from "./registry";
import { niceStep, parseTpoArgs, TPO_USAGE as USAGE, tpoDay, type TpoDay } from "./tpoMath";
import { useEnvelope } from "./useEnvelope";

/** Exchange-local calendar day of each bar. One formatter per zone (making one per bar is slow). */
function dayKeys(t: Float64Array | number[], tz: string | null): string[] {
  const f = new Intl.DateTimeFormat("en-CA", { timeZone: tz || "UTC", year: "numeric", month: "2-digit", day: "2-digit" });
  return Array.from(t, (x) => f.format(new Date(x * 1000)));
}

export default function TPO({ panelId, security, args }: FunctionProps) {
  const p = useMemo(() => parseTpoArgs(args, security?.symbol), [args, security?.symbol]);
  const range = p.days <= 1 ? "1D" : p.days <= 5 ? "5D" : "1M";
  const { env, error, loading, reload } = useEnvelope(`${p.symbol}:${range}`, (fresh) => marketApi.history(p.symbol, range, "5m", fresh));
  usePanelRefresh(panelId, () => void reload(true));

  // Days -> profiles, all on one price grid (one row height) so the columns line up.
  const view = useMemo(() => {
    if (!env || p.error) return null;
    const d = env.data;
    const t = Array.from(d.t as ArrayLike<number>);
    const h = Array.from(d.h as ArrayLike<number | null>, (x) => (x == null ? NaN : x));
    const l = Array.from(d.l as ArrayLike<number | null>, (x) => (x == null ? NaN : x));
    const keys = dayKeys(t, d.tz ?? null);
    const order = [...new Set(keys)].slice(-p.days);
    let lo = Infinity;
    let hi = -Infinity;
    for (let i = 0; i < t.length; i++)
      if (order.includes(keys[i]) && Number.isFinite(h[i]) && Number.isFinite(l[i])) {
        lo = Math.min(lo, l[i]);
        hi = Math.max(hi, h[i]);
      }
    if (!Number.isFinite(lo)) return { days: [] as TpoDay[], step: 1, lo: 0, rows: 0 };
    const step = niceStep(hi - lo, 40);
    const days = order
      .map((day) => {
        const idx = keys.flatMap((k, i) => (k === day ? [i] : []));
        return tpoDay(day, idx.map((i) => t[i]), idx.map((i) => h[i]), idx.map((i) => l[i]), p.bracket * 60, step);
      })
      .filter((x): x is TpoDay => x !== null);
    const gLo = Math.floor(lo / step) * step;
    return { days, step, lo: gLo, rows: Math.floor((hi - gLo) / step) + 1 };
  }, [env, p.error, p.days, p.bracket]);

  const decimals = view ? Math.max(0, Math.min(6, -Math.floor(Math.log10(view.step)))) : 2;
  const width = view ? Math.max(4, ...view.days.flatMap((d) => d.rows.map((r) => r.length))) : 4;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">TPO {p.symbol}</span> {p.days} DAYS · {p.bracket} MIN BRACKETS · FROM 5MIN BARS (EXACT FOR THOSE BARS)
        <EnvStatus env={env} loading={loading} />
      </div>
      {p.error && <div className="err">{p.error}</div>}
      <ErrorLine error={error} hasData={!!env} usage={USAGE} />
      {view && !view.days.length && !loading && <div className="dim">NO INTRADAY BARS IN THIS RANGE</div>}
      {view && view.days.length > 0 && (
        <>
          <div className="dim">
            <span className="warn">POC</span> = MOST TIME · <span className="acc">VALUE AREA</span> = 70% OF TIME · IB = FIRST 2 BRACKETS · LETTERS A, B, C … = BRACKETS IN ORDER
          </div>
          <pre className="desc" data-testid="tpo-grid">
            {/* Header: one column per day. */}
            {`${"PRICE".padStart(10)}  ${view.days.map((d) => d.day.slice(5).padEnd(width)).join(" ")}\n`}
            {Array.from({ length: view.rows }, (_, k) => view.rows - 1 - k).map((g) => {
              const price = view.lo + g * view.step;
              return (
                <span key={g}>
                  {fmtNum(price, decimals).padStart(10)}{"  "}
                  {view.days.map((d, j) => {
                    const r = Math.round((price - d.lo) / d.step);
                    const text = (d.rows[r] ?? "").padEnd(width);
                    const cls = r === d.poc ? "warn" : r >= d.vaLo && r <= d.vaHi && d.rows[r] ? "acc" : "dim";
                    return (
                      <span key={d.day} className={cls}>
                        {j ? " " : ""}
                        {text}
                      </span>
                    );
                  })}
                  {"\n"}
                </span>
              );
            })}
          </pre>
          {view.days.map((d) => (
            <div key={d.day} className="line">
              <span className="acc">{d.day}</span> POC {fmtNum(d.lo + (d.poc + 0.5) * d.step, decimals)} · VA {fmtNum(d.lo + d.vaLo * d.step, decimals)}–
              {fmtNum(d.lo + (d.vaHi + 1) * d.step, decimals)} · IB {fmtNum(d.ibLo, decimals)}–{fmtNum(d.ibHi, decimals)} · {d.singles.length} SINGLE PRINTS
              {d.poorHigh && <span className="warn"> · POOR HIGH</span>}
              {d.poorLow && <span className="warn"> · POOR LOW</span>}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
