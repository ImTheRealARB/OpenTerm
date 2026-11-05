/**
 * MF: Indian mutual funds from MFapi.in (a free community service that republishes AMFI's daily NAV; not an official AMFI API, may lag a day).
 *
 *   MF parag parikh     lists schemes whose name has every word. Up/Down move, Enter opens the highlighted fund.
 *   MF 122639           one fund: latest NAV and its date, 1D 1W 1M 3M 6M 1Y 3Y 5Y returns, and the NAV chart.
 *
 * NAV (net asset value) is the price of one unit of the fund, set once a day after markets close. Returns are worked out on the server from the NAV
 * series (`world/mfund.py`): up to 1Y an ABSOLUTE RETURN, over 1Y a CAGR (compound annual growth rate), each from the nearest NAV on or before the
 * target date, whose date the table shows. A period the history does not reach shows "-" and says why; nothing is estimated.
 * Keys: Up/Down (or J/K) move in the table; fund view: C line/area, X crosshair, Left/Right (or H/L) pan or step the crosshair, +/- zoom; E CSV, F5 refresh.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ChartView, type BarData, type ChartHandle, type ChartType } from "../chart/ChartView";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { worldApi, type MfFund, type MfReturnRow, type MfSearchRow } from "../net/api";
import { navigate } from "../state/workspace";
import { useEnvLoad } from "./cryptoLoad";
import { EnvStatus, ErrorLine } from "./macroUi";
import { fmtNav, fmtPct, isoOfEpoch, MF_USAGE, NAV_NORMAL_AGE_DAYS, navAgeDays, navAgeText, parseMfArgs, searchHeadline } from "./mfArgs";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

const NO_INDICATORS: never[] = [];

const SEARCH_COLS: Column<MfSearchRow>[] = [
  { title: "CODE", width: 9, text: (r) => String(r.code), color: () => "acc" },
  { title: "SCHEME", width: 110, text: (r) => r.name },
];
const RETURN_COLS: Column<MfReturnRow>[] = [
  { title: "PERIOD", width: 7, text: (r) => r.period, color: () => "acc" },
  { title: "MEASURE", width: 16, text: (r) => r.kind, color: () => "dim" },
  { title: "RETURN", width: 10, align: "right", text: (r) => fmtPct(r.pct), color: (r) => (r.pct == null ? "dim" : r.pct > 0 ? "up" : r.pct < 0 ? "down" : "fg") },
  { title: "BASE DATE", width: 11, text: (r) => r.base_date ?? "-", color: () => "dim" },
  { title: "BASE NAV", width: 10, align: "right", text: (r) => fmtNav(r.base_nav), color: () => "dim" },
  { title: "WHY NO NUMBER", width: 44, text: (r) => r.why ?? "", color: () => "warn" },
];

/** The NAV series as chart bars: a line has one value per day, so open/high/low/close are all the NAV and volume is zero. */
function toBars(f: MfFund): BarData {
  const c = Float64Array.from(f.v);
  return { symbol: `MF.${f.code}`, interval: "1d", tz: "UTC", t: Float64Array.from(f.t), o: c, h: c, l: c, c, v: new Float64Array(c.length) };
}

export default function MF({ panelId, args }: FunctionProps) {
  const p = useMemo(() => parseMfArgs(args), [args]);
  if (p.error) {
    return (
      <div className="fn">
        <div className="line"><span className="acc">MF</span> · {p.error}</div>
        <div className="dim">EXAMPLES: MF PARAG PARIKH · MF NIFTY INDEX DIRECT · MF 122639</div>
      </div>
    );
  }
  return <MfView panelId={panelId} q={p.q} />;
}

function MfView({ panelId, q }: { panelId: number; q: string }) {
  const { env, error, loading, load } = useEnvLoad((fresh) => worldApi.mf(q, fresh), q.toLowerCase());
  const grid = useRef<GridHandle>(null);
  const chart = useRef<ChartHandle>(null);
  const [type, setType] = useState<ChartType>("LINE");
  const [crossOn, setCrossOn] = useState(false);
  const d = env?.data;
  const search = d?.mode === "SEARCH" ? d : null;
  const fund = d?.mode === "FUND" ? d : null;
  const bars = useMemo(() => (fund ? toBars(fund) : null), [fund]);
  const rowCount = search?.items.length ?? fund?.returns.length ?? 0;
  const latest = useLatest({ search, rowCount, crossOn });

  // E / Alt+X: the search list, or (for a fund) the whole NAV series, which is more useful in a spreadsheet than the 8-row returns table.
  useCsvExport(panelId, () => {
    if (search) return gridCsv("MF_SEARCH", SEARCH_COLS, search.items);
    if (!fund) return null;
    return { name: `MF_${fund.code}_NAV`, header: ["date", "nav"], rows: fund.t.map((t, i) => [isoOfEpoch(t), String(fund.v[i])]) };
  });

  useEffect(() => {
    setCrossOn(false);
  }, [q]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const cur = latest.current;
        if (navKey(e, grid.current, cur.rowCount)) return true;
        switch (e.key) {
          case "F5":
            void load(true);
            return true;
          case "Enter": {
            const row = cur.search?.items[grid.current?.selected() ?? -1];
            if (row) navigate(panelId, { fn: "MF", args: [String(row.code)], security: undefined });
            return !!row;
          }
          // The chart keys only act in the fund view (there is no chart in the search list).
          case "c":
          case "C":
            if (cur.search) return false;
            setType((t) => (t === "LINE" ? "AREA" : "LINE"));
            return true;
          case "x":
          case "X": {
            if (cur.search) return false;
            const on = !cur.crossOn;
            chart.current?.crosshair(on);
            setCrossOn(on);
            return true;
          }
          case "ArrowLeft":
          case "h":
          case "H":
            if (cur.search) return false;
            if (cur.crossOn) chart.current?.crosshairStep(-1);
            else chart.current?.pan(-5);
            return true;
          case "ArrowRight":
          case "l":
          case "L":
            if (cur.search) return false;
            if (cur.crossOn) chart.current?.crosshairStep(1);
            else chart.current?.pan(5);
            return true;
          case "+":
          case "=":
            chart.current?.zoom(0.8);
            return !cur.search;
          case "-":
            chart.current?.zoom(1.25);
            return !cur.search;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  const age = fund ? navAgeDays(fund.latest.date, Date.now()) : 0;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">MF</span> {fund ? fund.name.toUpperCase() : search ? `SEARCH "${q.toUpperCase()}"` : /^\d+$/.test(q) ? `SCHEME ${q}` : `SEARCH "${q.toUpperCase()}"`}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · {search ? "ENTER OPEN FUND · " : "C LINE/AREA · X CROSS · ←/→ PAN · +/- ZOOM · "}E CSV · F5</span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage={MF_USAGE} />
      {d && <div className="dim">{d.source_note}</div>}
      {search && (
        <>
          <div className="line">{searchHeadline(search.total, search.shown, search.query)}</div>
          <div className="dim">{search.note}</div>
          <Grid key="search" ref={grid} columns={SEARCH_COLS} rows={search.items} />
        </>
      )}
      {fund && (
        <>
          <div className="line">
            {fund.fund_house.toUpperCase()}
            <span className="dim"> · {fund.category.toUpperCase()} · {fund.scheme_type.toUpperCase()} · SCHEME {fund.code}</span>
            {(fund.isin_growth || fund.isin_div) && <span className="dim"> · ISIN {fund.isin_growth ?? fund.isin_div}</span>}
          </div>
          <div className="line">
            NAV <span className="acc">{fmtNav(fund.latest.nav)}</span> INR PER UNIT ON {fund.latest.date}
            <span className={age > NAV_NORMAL_AGE_DAYS ? "warn" : "dim"}> · {navAgeText(age)}{age > NAV_NORMAL_AGE_DAYS ? " (NO NEWER NAV FROM THE SOURCE)" : ""}</span>
            <span className="dim"> · {fund.points} DAILY NAVS SINCE {fund.first_date}</span>
          </div>
          <div className={fund.payout_plan ? "warn" : "dim"}>{fund.note}</div>
          <Grid key="returns" ref={grid} columns={RETURN_COLS} rows={fund.returns} />
          {bars && (
            <div className="vis" data-testid="mf-chart">
              <div className="line dim">NAV PER UNIT, DAILY{crossOn ? " · CROSSHAIR (←/→, X TO EXIT)" : ""}</div>
              <div className="xychart">
                <ChartView key={fund.code} ref={chart} data={bars} type={type} log={false} indicators={NO_INDICATORS} readoutLabel="NAV" />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
