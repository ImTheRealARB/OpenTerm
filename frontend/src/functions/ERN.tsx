/** Earnings calendar (Nasdaq.com): estimates for upcoming days, reported EPS and surprise for past days.
 * Phase 32 earnings card: A on a row opens `AI FILING <SYM> EARNINGS` beside this panel (the release's revenue, EPS and guidance, each
 * claim quoted from the 8-K Exhibit 99.1), so the row's EPS vs estimate and surprise stay in view next to it. US SEC filers only. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtBig, fmtNum, fmtPct } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { ApiError } from "../net/core";
import { macroApi } from "../net/macroApi";
import type { Earning, EarningsPayload, Envelope } from "../net/types";
import { navigate, replaceView } from "../state/workspace";
import { askAi } from "./askAi";
import { addDays, dayLabel, isWeekend, nyToday, parseErnArgs } from "./macroArgs";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const POLL_MS = 120_000;
const eps = (v: number | null) => (v == null ? "-" : fmtNum(v, 2));

const COLUMNS: Column<Earning>[] = [
  { title: "SECURITY", width: 8, text: (r) => r.symbol, color: () => "acc" },
  { title: "COMPANY", width: 30, text: (r) => r.name ?? "", color: () => "dim" },
  { title: "WHEN", width: 5, text: (r) => r.time ?? "-", color: (r) => (r.time ? "fg" : "dim") },
  { title: "QTR END", width: 8, text: (r) => r.fiscal_quarter ?? "-", color: () => "dim" },
  { title: "EPS EST", width: 8, align: "right", text: (r) => eps(r.eps_forecast) },
  { title: "#EST", width: 5, align: "right", text: (r) => (r.n_ests == null ? "-" : String(r.n_ests)), color: () => "dim" },
  { title: "LAST YR", width: 8, align: "right", text: (r) => eps(r.last_year_eps), color: () => "dim" },
  { title: "EPS", width: 8, align: "right", text: (r) => eps(r.eps) },
  {
    title: "SURPRISE",
    width: 9,
    align: "right",
    text: (r) => (r.surprise_pct == null ? "-" : fmtPct(r.surprise_pct)),
    color: (r) => ((r.surprise_pct ?? 0) > 0 ? "up" : (r.surprise_pct ?? 0) < 0 ? "down" : "dim"),
  },
  { title: "MKT CAP", width: 9, align: "right", text: (r) => fmtBig(r.market_cap) },
];

/** The calendar's own name from the envelope source: "nasdaq_earnings" -> NASDAQ, "finnhub + yahoo_screener (...)" -> FINNHUB
 * (Finnhub answers while Nasdaq blocks OpenTerm, 2026-11-26). */
const calendarName = (source: string): string => source.split(/[_\s]/)[0].toUpperCase();

export default function ERN({ panelId, args }: FunctionProps) {
  const parsed = useMemo(() => parseErnArgs(args, nyToday()), [args]);
  const date = parsed.ok ? parsed.date : null;
  const [env, setEnv] = useState<Envelope<EarningsPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const grid = useRef<GridHandle>(null);

  const load = useCallback(
    (fresh: boolean) => {
      if (!date) return Promise.resolve();
      setLoading(true);
      return macroApi
        .earnings(date, fresh)
        .then((e) => {
          setEnv(e);
          setError(null);
        })
        .catch((e: ApiError) => setError(e))
        .finally(() => setLoading(false));
    },
    [date],
  );

  useEffect(() => {
    setEnv(null);
    void load(false);
    const t = setInterval(() => void load(false), POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  const cur = env && env.data.date === date ? env : null;
  const rows = useMemo(() => cur?.data.rows ?? [], [cur]);
  const latest = useLatest({ rows, date });
  useCsvExport(panelId, () => gridCsv(`ERN_${date ?? ""}`, COLUMNS, rows));

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const { rows: r, date: d } = latest.current;
        if (navKey(e, g, r.length)) return true;
        const go = (iso: string) => replaceView(panelId, (v) => ({ ...v, args: [iso] }));
        switch (e.key) {
          case "ArrowLeft":
            if (d) go(addDays(d, -1));
            return true;
          case "ArrowRight":
            if (d) go(addDays(d, 1));
            return true;
          case "t":
            go(nyToday());
            return true;
          case "a":
          case "A": {
            const row = r[g?.selected() ?? -1];
            if (!row) return true;
            if (row.eps == null) setNote(`${row.symbol} HAS NOT REPORTED YET: THE EARNINGS CARD NEEDS ITS RELEASE`);
            else {
              setNote(null);
              askAi(`FILING ${row.symbol} EARNINGS`, setNote);
            }
            return true;
          }
          case "Enter": {
            const row = r[g?.selected() ?? -1];
            if (row) navigate(panelId, { fn: "DES", security: { symbol: row.symbol }, args: [] });
            return true;
          }
        }
        return false;
      }),
    [panelId, latest],
  );

  const reported = rows.filter((r) => r.eps != null).length;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">EARNINGS</span>
        {date && ` · ${dayLabel(date)}`}
        {cur && ` · ${rows.length} REPORTS`}
        {cur && rows.length > 0 && ` · ${reported} REPORTED`}
        <EnvStatus env={cur} loading={loading} />
        <span className="dim legend"> · J/K MOVE · ←/→ DAY · T TODAY · ENTER DES · A EARNINGS CARD (AI) · E CSV · F5 REFRESH</span>
      </div>
      {!parsed.ok && <div className="err">{parsed.error}</div>}
      {cur && rows.length === 0 && (
        <div className="dim">
          {calendarName(cur.data.source)} LISTS NO REPORTS FOR {date}
          {date && isWeekend(date) ? " (WEEKEND)." : " (HOLIDAY, OR NOT SCHEDULED YET)."} ←/→ CHANGES THE DAY.
        </div>
      )}
      {cur && rows.length > 0 && <div className="dim">SORTED BY MARKET CAP · EPS EST = CONSENSUS ({cur.data.as_of_text?.toUpperCase() ?? calendarName(cur.data.source)}) · ESTIMATES, NOT ACTUALS, UNTIL A COMPANY REPORTS</div>}
      {note && <div className="line acc" data-testid="ern-note">{note}</div>}
      <ErrorLine error={error} hasData={!!cur} usage="ERN [TODAY|TOMORROW|+N|-N|YYYY-MM-DD]" />
      <Grid ref={grid} columns={COLUMNS} rows={rows} />
    </div>
  );
}
