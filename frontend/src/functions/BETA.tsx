/**
 * BETA: how much a security moves with a benchmark, from a least-squares line through their returns.
 *
 *   BETA AAPL                       2 years of daily returns against SPY
 *   BETA AAPL VS QQQ 5Y W WIN=26    weekly returns, rolling beta over the last 26 returns
 *
 * The server does the regression (`/api/world/beta`); this panel shows beta, alpha, R-squared, the standard error, the adjusted
 * beta (0.67 x raw + 0.33, the usual pull toward 1), a scatter of the returns with the fitted line, and a rolling beta.
 * It is a statement about the past, not a forecast. Keys: R next range, P next return period (D, W, M), E CSV, F5 refresh.
 */
import { useEffect, useMemo } from "react";
import { ChartView } from "../chart/ChartView";
import { registerPanelKeys } from "../keys/panelKeys";
import { returnsApi } from "../net/returnsApi";
import type { BetaPayload } from "../net/returnsTypes";
import { useLatest } from "../state/useLatest";
import { replaceView } from "../state/workspace";
import { BetaScatter } from "./BetaScatter";
import { usePanelRefresh } from "./panelRefresh";
import { EnvStatus, ErrorLine } from "./panelStatus";
import type { FunctionProps } from "./registry";
import { useCsvExport } from "./tableExport";
import { type BetaPeriod, betaViewArgs, datedBars, nextPeriod, nextRange, num, parseBetaArgs, PERIOD_WORD, signedPct } from "./traBeta";
import "./traBeta.css";
import { useEnvelope } from "./useEnvelope";

export default function BETA({ panelId, security, args }: FunctionProps) {
  // The security is the panel's own (BETA needs one); a symbol typed in the args wins. A usage error is shown and nothing is fetched.
  const parsed = useMemo(() => parseBetaArgs(args, security?.symbol), [args, security?.symbol]);
  if (parsed.error) {
    return (
      <div className="fn">
        <div className="line">
          <span className="acc">BETA</span> REGRESSION AGAINST A BENCHMARK
        </div>
        <div className="err">{parsed.error}</div>
      </div>
    );
  }
  return <BetaView panelId={panelId} symbol={parsed.symbol} vs={parsed.vs} range={parsed.range} per={parsed.per} win={parsed.win} />;
}

interface ViewProps {
  panelId: number;
  symbol: string;
  vs: string;
  range: string;
  per: BetaPeriod;
  win: number;
}

function BetaView({ panelId, symbol, vs, range, per, win }: ViewProps) {
  const key = `${symbol}|${vs}|${range}|${per}|${win}`;
  const { env, error, loading, reload } = useEnvelope<BetaPayload>(key, (fresh) => returnsApi.beta(symbol, vs, range, per, win, fresh));
  usePanelRefresh(panelId, () => { void reload(true); });

  const d = env?.data;
  const latest = useLatest({ symbol, vs, range, per, win });

  // The rolling beta as chart bars. Dates arrive as text, the chart wants epoch seconds.
  const rolling = useMemo(() => (d && d.rolling.dates.length ? datedBars(`BETA ${d.rolling.win}`, d.rolling.dates, d.rolling.beta) : null), [d]);

  useCsvExport(panelId, () =>
    d
      ? {
          name: `BETA_${symbol}_${vs}_${range}_${per}`,
          header: ["benchmark_return_pct", "security_return_pct"],
          rows: d.scatter.x.map((x, i) => [x, d.scatter.y[i]]),
        }
      : null,
  );

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const s = latest.current;
        const k = e.key.toLowerCase();
        // The settings go into the view's args (so a saved layout reopens on them); the changed args are a new load.
        if (k === "r") {
          replaceView(panelId, (v) => ({ ...v, args: betaViewArgs({ ...s, range: nextRange(s.range) }) }));
          return true;
        }
        if (k === "p") {
          replaceView(panelId, (v) => ({ ...v, args: betaViewArgs({ ...s, per: nextPeriod(s.per) }) }));
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">BETA</span> {symbol} VS {vs} · {range} · {PERIOD_WORD[per]} RETURNS
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · R RANGE · P D/W/M · E CSV · F5 REFRESH</span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage="BETA SYM [VS BENCHMARK] [1M..MAX] [D|W|M] [WIN=60]" />
      {d && (
        <>
          <div className="kv" data-testid="beta-stats">
            <div><span>BETA</span><span className="acc">{num(d.beta, 3)}</span></div>
            <div><span>ADJUSTED BETA</span><span>{num(d.adj_beta, 3)}</span></div>
            <div><span>STD ERROR OF BETA</span><span>{num(d.se_beta, 3)}</span></div>
            <div><span>R-SQUARED</span><span>{d.r2 == null ? "—" : num(d.r2, 3)}</span></div>
            <div><span>ALPHA PER {PERIOD_WORD[d.per]} PERIOD</span><span className={d.alpha_pct >= 0 ? "up" : "down"}>{signedPct(d.alpha_pct, 3)}</span></div>
            <div><span>ALPHA PER YEAR (x {d.periods_per_year})</span><span className={d.alpha_annual_pct >= 0 ? "up" : "down"}>{signedPct(d.alpha_annual_pct)}</span></div>
            <div><span>OBSERVATIONS</span><span>{d.n}</span></div>
            <div><span>DATES</span><span>{d.first} TO {d.last}</span></div>
          </div>
          <div className="dim">
            {d.basis} · ADJUSTED BETA = 0.67 x RAW + 0.33 · SOURCES: {Object.entries(d.sources).map(([s, src]) => `${s} ${String(src).toUpperCase()}`).join(", ")} · ALPHA IS BEFORE ANY RISK-FREE RATE · PAST DATA, NOT A FORECAST
          </div>
          {d.r2 == null && <div className="warn">R-SQUARED IS EMPTY: THE SECURITY'S RETURNS DID NOT VARY OVER THIS RANGE</div>}
          {d.n < 30 && <div className="warn">ONLY {d.n} RETURNS: A THIN SAMPLE, THE BETA IS UNRELIABLE. TRY A LONGER RANGE OR A FINER PERIOD</div>}
          <div className="vis">
            <div className="tb-pair">
              <div className="tb-half">
                <div className="dim">RETURNS: {d.symbol} (Y) AGAINST {d.benchmark} (X), PERCENT, WITH THE FITTED LINE</div>
                <BetaScatter
                  x={d.scatter.x}
                  y={d.scatter.y}
                  beta={d.beta}
                  alphaPct={d.alpha_pct}
                  xLabel={`${d.benchmark} RETURN %`}
                  yLabel={`${d.symbol} RETURN %`}
                />
              </div>
              <div className="tb-half">
                {rolling ? (
                  <>
                    <div className="dim">ROLLING BETA OVER THE LAST {d.rolling.win} {PERIOD_WORD[d.per]} RETURNS</div>
                    <ChartView key={`${key}:${env?.as_of}`} data={rolling} type="LINE" log={false} readoutLabel={`BETA ${d.rolling.win}`} />
                  </>
                ) : (
                  <div className="warn">
                    ONLY {d.n} RETURNS, FEWER THAN THE {d.rolling.win} A ROLLING BETA NEEDS: NO ROLLING LINE. USE A LONGER RANGE OR A SMALLER WIN=
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
