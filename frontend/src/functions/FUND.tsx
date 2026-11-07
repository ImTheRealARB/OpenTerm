/**
 * FUND: perpetual funding and basis. `FUND` = the board of majors (Binance USD-M, OKX when Binance fails) plus Binance dated quarterlies;
 * `FUND BTC` = one perpetual with its last 30 funding prints. Funding is annualised from the venue's own interval (8h / 4h / 1h); a perpetual's
 * premium (mark vs index) is not annualised, a quarterly's basis is (x 365 / days to expiry). Keys: Enter opens the coin, Backspace back to the board,
 * E CSV, F5 refresh.
 */
import { useEffect, useMemo, useRef } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtPrice } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import type { FundRow } from "../net/types";
import { worldApi } from "../net/worldApi";
import { navigate } from "../state/workspace";
import { countdown, joinArg, sPct, signClass, utc } from "./cryptoArgs";
import { useEnvelope } from "./useEnvelope";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

type Print = { t: number; rate_pct: number; ann_pct: number };

const BOARD: Column<FundRow>[] = [
  { title: "CONTRACT", width: 15, text: (r) => r.sym, color: () => "acc" },
  { title: "KIND", width: 9, text: (r) => r.kind, color: () => "dim" },
  { title: "MARK", width: 11, align: "right", text: (r) => fmtPrice(r.mark) },
  { title: "INDEX", width: 11, align: "right", text: (r) => fmtPrice(r.index) },
  { title: "BASIS", width: 8, align: "right", text: (r) => sPct(r.basis_pct, 3), color: (r) => signClass(r.basis_pct) },
  { title: "FUNDING", width: 9, align: "right", text: (r) => sPct(r.rate_pct, 4), color: (r) => signClass(r.rate_pct) },
  { title: "EVERY", width: 5, align: "right", text: (r) => (r.interval_h ? `${r.interval_h}H` : "") },
  { title: "ANNUAL", width: 8, align: "right", text: (r) => sPct(r.ann_pct ?? r.ann_basis_pct, 2), color: (r) => signClass(r.ann_pct ?? r.ann_basis_pct) },
  { title: "NEXT / EXPIRY", width: 13, text: (r) => (r.expiry ? `${r.expiry} ${r.days}D` : countdown(r.next_ms, Date.now())), color: () => "dim" },
  { title: "VENUE", width: 8, text: (r) => r.source.toUpperCase(), color: () => "dim" },
];
const PRINTS: Column<Print>[] = [
  { title: "SETTLED (UTC)", width: 20, text: (r) => utc(r.t), color: () => "dim" },
  { title: "RATE", width: 10, align: "right", text: (r) => sPct(r.rate_pct, 4), color: (r) => signClass(r.rate_pct) },
  { title: "ANNUALISED", width: 11, align: "right", text: (r) => sPct(r.ann_pct, 2), color: (r) => signClass(r.ann_pct) },
];

export default function FUND({ panelId, args }: FunctionProps) {
  const sym = useMemo(() => joinArg(args).toUpperCase(), [args]);
  const { env, error, loading, reload: load } = useEnvelope(sym, (fresh) => worldApi.fund(sym, fresh), 30_000);
  const grid = useRef<GridHandle>(null);
  const d = env?.data;
  const rows = useMemo(() => d?.rows ?? [], [d]);
  const prints = useMemo(() => (d?.detail ? [...d.detail.prints].reverse() : []), [d]);
  const latest = useLatest({ rows, prints, detail: !!d?.detail });
  useCsvExport(panelId, () => (d ? (d.detail ? gridCsv(`FUND_${sym}`, PRINTS, prints) : gridCsv("FUND", BOARD, rows)) : null));

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const cur = latest.current;
        const g = grid.current;
        if (navKey(e, g, cur.detail ? cur.prints.length : cur.rows.length)) return true;
        if (e.key === "Enter" && !cur.detail) {
          const r = cur.rows[g?.selected() ?? -1];
          if (r && r.kind === "PERP") navigate(panelId, { fn: "FUND", args: [r.base], security: undefined });
          return true;
        }
        if (e.key === "Backspace" && cur.detail) {
          navigate(panelId, { fn: "FUND", args: [], security: undefined });
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  const h = d?.detail;
  return (
    <div className="fn">
      <div className="line">
        <span className="acc">FUND</span> PERPETUAL FUNDING · {d?.mode === "DETAIL" ? rows[0]?.sym : "MAJORS"}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · {d?.detail ? "BACKSPACE BOARD" : "ENTER COIN"} · E CSV · F5</span>
      </div>
      <div className="dim">
        ANNUAL = RATE X PRINTS PER DAY X 365 (SIMPLE, NOT COMPOUNDED). PERP BASIS = MARK VS INDEX, NOT ANNUALISED; QUARTERLY ANNUAL = BASIS X 365 / DAYS TO EXPIRY.
      </div>
      {h && (
        <div className="line" data-testid="fund-mean">
          LAST {h.prints.length} PRINTS: MEAN <span className={signClass(h.mean_rate_pct)}>{sPct(h.mean_rate_pct, 4)}</span> EVERY {h.interval_h}H = {sPct(h.mean_ann_pct, 2)} A YEAR
        </div>
      )}
      <ErrorLine error={error} hasData={!!d} usage="FUND [BTC]" />
      {h && rows[0] && (
        <div className="line">
          {rows[0].sym} MARK {fmtPrice(rows[0].mark)} · INDEX {fmtPrice(rows[0].index)} · BASIS <span className={signClass(rows[0].basis_pct)}>{sPct(rows[0].basis_pct, 3)}</span> · NOW{" "}
          <span className={signClass(rows[0].rate_pct)}>{sPct(rows[0].rate_pct, 4)}</span> = {sPct(rows[0].ann_pct, 2)} A YEAR · NEXT {countdown(rows[0].next_ms, Date.now()) || "—"} · {rows[0].source.toUpperCase()}
        </div>
      )}
      {h ? <Grid ref={grid} columns={PRINTS} rows={prints} /> : <Grid ref={grid} columns={BOARD} rows={rows} />}
    </div>
  );
}
