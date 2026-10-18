/**
 * STBL: stablecoin supply (DefiLlama). `STBL` = coins by circulating USD with 1d / 7d / 30d change and peg deviation; `STBL TRON` = supply on one chain.
 * Keys: C switches COINS / CHAINS, Enter on a chain opens STBL <chain>, Backspace back to all chains, E CSV, F5 refresh.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { fmtBig, fmtRate } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { worldApi, type StblCoin, type StblPayload } from "../net/api";
import { navigate } from "../state/workspace";
import { joinArg, sPct, signClass } from "./cryptoArgs";
import { useEnvLoad } from "./cryptoLoad";
import { EnvStatus, ErrorLine } from "./macroUi";
import { navKey, useLatest } from "./quoteRows";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

type ChainRow = StblPayload["chains"][number];

const COINS: Column<StblCoin>[] = [
  { title: "SYMBOL", width: 8, text: (r) => r.symbol, color: () => "acc" },
  { title: "NAME", width: 22, text: (r) => r.name },
  { title: "PEG", width: 10, text: (r) => r.peg.replace("pegged", ""), color: () => "dim" },
  { title: "SUPPLY $", width: 10, align: "right", text: (r) => fmtBig(r.value) },
  { title: "1D", width: 7, align: "right", text: (r) => sPct(r.chg_1d), color: (r) => signClass(r.chg_1d) },
  { title: "7D", width: 7, align: "right", text: (r) => sPct(r.chg_7d), color: (r) => signClass(r.chg_7d) },
  { title: "30D", width: 7, align: "right", text: (r) => sPct(r.chg_30d), color: (r) => signClass(r.chg_30d) },
  { title: "PRICE", width: 8, align: "right", text: (r) => (r.price == null ? "" : fmtRate(r.price)) },
  { title: "PEG DEV", width: 8, align: "right", text: (r) => sPct(r.peg_dev_pct), color: (r) => (r.peg_dev_pct != null && Math.abs(r.peg_dev_pct) >= 0.5 ? "warn" : "dim") },
  { title: "MECHANISM", width: 15, text: (r) => r.mechanism ?? "", color: () => "dim" },
  { title: "TOP CHAINS", width: 34, text: (r) => r.chains.join(" "), color: () => "dim" },
];
const CHAINS: Column<ChainRow>[] = [
  { title: "CHAIN", width: 18, text: (r) => r.chain, color: () => "acc" },
  { title: "SUPPLY $", width: 10, align: "right", text: (r) => fmtBig(r.usd) },
  { title: "SHARE", width: 8, align: "right", text: (r) => (r.share_pct == null ? "" : r.share_pct.toFixed(2) + "%") },
];

export default function STBL({ panelId, args }: FunctionProps) {
  const chain = useMemo(() => joinArg(args), [args]);
  const { env, error, loading, load } = useEnvLoad((fresh) => worldApi.stbl(chain, fresh), chain.toLowerCase());
  const [view, setView] = useState<"COINS" | "CHAINS">("COINS");
  const grid = useRef<GridHandle>(null);
  const d = env?.data;
  const coins = useMemo(() => d?.coins ?? [], [d]);
  const chains = useMemo(() => d?.chains ?? [], [d]);
  const latest = useLatest({ coins, chains, view, chain });
  useCsvExport(panelId, () => (d ? (view === "COINS" ? gridCsv("STBL", COINS, coins) : gridCsv("STBL_CHAINS", CHAINS, chains)) : null));

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const cur = latest.current;
        const g = grid.current;
        if (navKey(e, g, cur.view === "COINS" ? cur.coins.length : cur.chains.length)) return true;
        if (e.key === "c" || e.key === "C") {
          setView((v) => (v === "COINS" ? "CHAINS" : "COINS"));
          return true;
        }
        if (e.key === "F5") {
          void load(true);
          return true;
        }
        if (e.key === "Enter" && cur.view === "CHAINS") {
          const r = cur.chains[g?.selected() ?? -1];
          if (r) navigate(panelId, { fn: "STBL", args: [r.chain], security: undefined });
          return true;
        }
        if (e.key === "Backspace" && cur.chain) {
          navigate(panelId, { fn: "STBL", args: [], security: undefined });
          return true;
        }
        return false;
      }),
    [panelId, latest, load],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">STBL</span> STABLECOINS · {d?.chain ? d.chain.toUpperCase() : "ALL CHAINS"} · {view}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · C COINS/CHAINS{view === "CHAINS" ? " · ENTER CHAIN" : ""}{chain ? " · BACKSPACE ALL" : ""} · E CSV · F5</span>
      </div>
      {d && (
        <div className="line" data-testid="stbl-summary">
          TOTAL ${fmtBig(d.total_usd)} {d.chain ? `ON ${d.chain.toUpperCase()}` : "ACROSS CHAINS"} · {d.n_coins} COINS
          <span className="dim"> · TOP {coins.length} SHOWN · CHAIN SHARE IS OF ALL STABLECOIN SUPPLY</span>
        </div>
      )}
      <ErrorLine error={error} hasData={!!d} usage="STBL [CHAIN]" />
      {view === "COINS" ? <Grid key="coins" ref={grid} columns={COINS} rows={coins} /> : <Grid key="chains" ref={grid} columns={CHAINS} rows={chains} />}
    </div>
  );
}
