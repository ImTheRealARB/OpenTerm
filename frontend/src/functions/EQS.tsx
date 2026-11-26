/** Equity screener over the whole US universe (Nasdaq screener download). Filter grammar: see eqsFilter.ts. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtAge, fmtBig, fmtChg, fmtPct, fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import { ApiError } from "../net/core";
import { marketApi } from "../net/marketApi";
import { researchApi } from "../net/researchApi";
import type { Envelope, EqsFundPayload, ScreenerPayload } from "../net/types";
import { navigate } from "../state/workspace";
import { FUND_FIELDS, parseFilter, screen, usesFund, type FundMap, type UniverseRow } from "./eqsFilter";
import { interpretNotes, interpretScreener, looksLikeEnglish } from "./eqsNatural";
import { dirColor } from "./quoteRows";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";
import EqsBt from "./EqsBt";
import { isEqsBt } from "./fundArgs";

const USAGE = "EQS SECTOR=TECH MCAP>10B PCT>2 PRICE<50 VOL>1M COUNTRY=US SORT=PCT  |  SEC FIGURES: ROE>15 MARGIN>10 GROWTH>5 DE<1 OPMARGIN>10";

/** `EQS BT ...` is the Phase 29 screen backtest (its own panel); anything else is the live screener below.
 *  The split happens in this wrapper so neither component calls hooks conditionally. */
export default function EQS(props: FunctionProps) {
  return isEqsBt(props.args) ? <EqsBt {...props} /> : <EqsScreen {...props} />;
}

function EqsScreen({ panelId, args }: FunctionProps) {
  const [env, setEnv] = useState<Envelope<ScreenerPayload> | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const grid = useRef<GridHandle>(null);
  // SEC formula fields (ROE, MARGIN, ...): fetched only once a term or the sort asks for one (about 5,000 filers; cached a day server side).
  const [fundEnv, setFundEnv] = useState<Envelope<EqsFundPayload> | null>(null);
  const [fundError, setFundError] = useState<ApiError | null>(null);

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

  // Plain English ("tech stocks with price under 50") is turned into EQS terms; real EQS syntax is used as typed.
  const english = useMemo(() => (looksLikeEnglish(args.join(" ")) ? interpretScreener(args.join(" ")) : null), [args]);
  const filter = useMemo(() => parseFilter(english ? english.args : args), [args, english]);
  const wantsFund = usesFund(filter);
  const fund = useMemo<FundMap | null>(() => fundEnv?.data.rows ?? null, [fundEnv]);
  const result = useMemo(() => (env ? screen(env.data, filter, fund) : null), [env, filter, fund]);
  const rows = useMemo(() => result?.rows ?? [], [result]);

  const loadFund = useCallback((fresh: boolean) => {
    return researchApi
      .eqsFund(fresh)
      .then((e) => {
        setFundEnv(e);
        setFundError(null);
      })
      .catch((e: ApiError) => setFundError(e));
  }, []);
  useEffect(() => {
    if (wantsFund && !fundEnv) void loadFund(false);
  }, [wantsFund, fundEnv, loadFund]);
  const latest = useLatest(rows);

  const columns = useMemo<Column<UniverseRow>[]>(() => {
    const d = env?.data;
    return [
      { title: "SYMBOL", width: 8, text: (r) => r[0], color: () => "acc" },
      { title: "NAME", width: 26, text: (r) => r[1], color: () => "dim" },
      { title: "LAST", width: 10, align: "right", text: (r) => fmtPrice(r[2]) },
      { title: "CHG", width: 8, align: "right", text: (r) => fmtChg(r[3]), color: (r) => dirColor(r[3]) },
      { title: "%CHG", width: 8, align: "right", text: (r) => fmtPct(r[4]), color: (r) => dirColor(r[4]) },
      { title: "VOLUME", width: 8, align: "right", text: (r) => fmtBig(r[5]) },
      { title: "MKT CAP", width: 8, align: "right", text: (r) => fmtBig(r[6]) },
      { title: "CTRY", width: 14, text: (r) => d?.countries[r[7]] ?? "", color: () => "dim" },
      { title: "SECTOR", width: 22, text: (r) => d?.sectors[r[9]] ?? "" },
      { title: "INDUSTRY", width: 30, text: (r) => d?.industries[r[10]] ?? "", color: () => "dim" },
      { title: "IPO", width: 4, align: "right", text: (r) => (r[8] == null ? "" : String(r[8])), color: () => "dim" },
      // The SEC columns appear only while a formula field is in use, so the plain screener keeps its width.
      ...(wantsFund && fund
        ? FUND_FIELDS.map((f, i): Column<UniverseRow> => ({
            title: f, width: 8, align: "right",
            text: (r) => {
              const v = fund[r[0]]?.[i];
              return v == null ? "" : f === "DE" ? v.toFixed(2) : `${v.toFixed(1)}%`;
            },
          }))
        : []),
    ];
  }, [env, wantsFund, fund]);

  useCsvExport(panelId, () => (result ? gridCsv(`EQS_${args.join("_") || "ALL"}`, columns, rows) : null));

  usePanelRefresh(panelId, () => { void load(true); if (wantsFund) void loadFund(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        const cur = latest.current;
        if (navKey(e, g, cur.length)) return true;
        switch (e.key) {
          case "Enter": {
            const r = cur[g?.selected() ?? -1];
            if (r) navigate(panelId, { fn: "DES", security: { symbol: r[0] }, args: [] });
            return true;
          }
        }
        return false;
      }),
    [panelId, latest],
  );

  const errors = result?.compiled.errors ?? filter.errors;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">EQS</span>
        {env && ` · ${env.data.count} IN UNIVERSE (${env.data.market.toUpperCase()}) · `}
        {result && <span className="acc">{rows.length} MATCH</span>}
        {result && result.compiled.terms.length > 0 && ` · ${result.compiled.terms.join(" ")}`}
        {result && result.compiled.terms.length === 0 && <span className="dim"> · NO FILTER (SORTED BY MKT CAP)</span>}
        {env && ` · ${(env.source ?? "").toUpperCase()}`}
        {env?.data.as_of_text && <span className="dim"> · {env.data.as_of_text.toUpperCase()}</span>}
        {env && <span className={env.stale ? "warn" : "dim"}> · {env.stale ? "STALE " : "AGE "}{fmtAge(env.age_s)}</span>}
        {loading && <span className="dim"> · LOADING…</span>}
        {wantsFund && fundEnv && <span className="dim"> · SEC FIGURES CY{fundEnv.data.year} ({fundEnv.data.source.toUpperCase()})</span>}
        {wantsFund && !fundEnv && !fundError && <span className="dim"> · LOADING SEC FIGURES…</span>}
        <span className="dim legend"> · J/K MOVE · ENTER DES · E CSV · F5 REFRESH</span>
      </div>
      {english && (
        <div data-testid="eqs-interp">
          <span className="acc">SHOWING:</span> {english.summary.length ? english.summary.join(", ") : "ALL SECURITIES"}
          <span className="dim"> · FROM "{args.join(" ").toUpperCase()}"</span>
        </div>
      )}
      {english && interpretNotes(english).map((n) => (
        <div key={n} className="warn" data-testid="eqs-interp-note">{n}</div>
      ))}
      {errors.length > 0 && <div className="err">{errors.join(" · ")} · EXAMPLE: {USAGE}</div>}
      {wantsFund && fundEnv && fundEnv.data.notes.map((n) => <div key={n} className="warn" data-testid="eqs-fund-note">{n}</div>)}
      {fundError && <div className="err">SEC FIGURES: {fundError.message}</div>}
      {error && (
        <div className="err">
          {error.message}
          {error.detail && <span className="dim"> ({error.detail})</span>}
        </div>
      )}
      {result && !rows.length && !errors.length && <div className="warn">NO SECURITIES MATCH THE FILTER</div>}
      <Grid ref={grid} columns={columns} rows={rows} />
    </div>
  );
}
