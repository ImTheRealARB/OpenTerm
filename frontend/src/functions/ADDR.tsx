/**
 * ADDR: an EVM address on Etherscan (free key ETHERSCAN_KEY, see APIKEYS): balance, the last 20 transactions and the gas price.
 * `ADDR 0xabc...` = Ethereum; add a chain nickname (ARB OP BASE POLY BSC) for another chain; `ADDR GAS` (or just `ADDR`) = gas price only.
 * Amounts are in the chain's own coin: no prices or fiat values are shown. Keys: arrows move, Enter shows the highlighted
 * transaction's full hash on a line, E CSV, F5 refresh. Read only: nothing here signs or sends anything.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Grid, type Column, type GridHandle } from "../components/Grid";
import { registerPanelKeys } from "../keys/panelKeys";
import { usePanelRefresh } from "./panelRefresh";
import type { AddrTx } from "../net/types";
import { worldApi } from "../net/worldApi";
import { agoText, addrQuery, fmtCoin, fmtGwei, shortHex, txTime } from "./addrArgs";
import { useEnvelope } from "./useEnvelope";
import { EnvStatus, ErrorLine } from "./panelStatus";
import { navKey } from "../keys/gridNav";
import { useLatest } from "../state/useLatest";
import type { FunctionProps } from "./registry";
import { gridCsv, useCsvExport } from "./tableExport";

export default function ADDR({ panelId, args }: FunctionProps) {
  const query = useMemo(() => addrQuery(args), [args]);
  const { env, error, loading, reload: load } = useEnvelope(query.toLowerCase(), (fresh) => worldApi.addr(query, fresh), 30_000);
  const grid = useRef<GridHandle>(null);
  const [picked, setPicked] = useState("");
  const d = env?.data;
  const txs = useMemo(() => d?.txs ?? [], [d]);
  const coin = d?.coin ?? "";
  const latest = useLatest({ txs });

  const columns = useMemo<Column<AddrTx>[]>(
    () => [
      { title: "TIME (UTC)", width: 17, text: (r) => txTime(r.time), color: () => "dim" },
      { title: "AGE", width: 5, align: "right", text: (r) => agoText(r.time, Date.now() / 1000), color: () => "dim" },
      { title: "DIR", width: 7, text: (r) => r.dir, color: (r) => (r.dir === "IN" ? "up" : r.dir === "OUT" ? "down" : "dim") },
      { title: `VALUE ${coin}`, width: 16, align: "right", text: (r) => fmtCoin(r.value) },
      { title: `FEE ${coin}`, width: 12, align: "right", text: (r) => fmtCoin(r.fee), color: () => "dim" },
      { title: "STATUS", width: 7, text: (r) => (r.failed ? "FAILED" : "OK"), color: (r) => (r.failed ? "warn" : "dim") },
      { title: "METHOD", width: 26, text: (r) => r.method, color: () => "dim" },
      { title: "FROM", width: 17, text: (r) => shortHex(r.from) },
      { title: "TO", width: 17, text: (r) => (r.to ? shortHex(r.to) : "CONTRACT CREATION") },
      { title: "HASH", width: 17, text: (r) => shortHex(r.hash), color: () => "acc" },
    ],
    [coin],
  );
  // The CSV carries the full hashes and addresses (the table shortens them).
  useCsvExport(panelId, () =>
    d && d.mode === "ADDRESS"
      ? gridCsv(`ADDR_${d.chain}_${d.address ?? ""}`.slice(0, 60), [
          { title: "TIME_UTC", width: 17, text: (r: AddrTx) => txTime(r.time) },
          { title: "DIR", width: 7, text: (r: AddrTx) => r.dir },
          { title: `VALUE_${coin}`, width: 16, text: (r: AddrTx) => String(r.value) },
          { title: `FEE_${coin}`, width: 12, text: (r: AddrTx) => (r.fee == null ? "" : String(r.fee)) },
          { title: "STATUS", width: 7, text: (r: AddrTx) => (r.failed ? "FAILED" : "OK") },
          { title: "METHOD", width: 26, text: (r: AddrTx) => r.method },
          { title: "FROM", width: 42, text: (r: AddrTx) => r.from ?? "" },
          { title: "TO", width: 42, text: (r: AddrTx) => r.to ?? "" },
          { title: "HASH", width: 66, text: (r: AddrTx) => r.hash },
        ], txs)
      : null,
  );

  usePanelRefresh(panelId, () => { void load(true); });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const g = grid.current;
        if (navKey(e, g, latest.current.txs.length)) return true;
        if (e.key === "Enter") {
          const r = latest.current.txs[g?.selected() ?? -1];
          if (r) setPicked(r.hash);
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">ADDR</span> {d ? `${d.chain} (CHAIN ${d.chainid})` : "EVM ADDRESS"} · {d ? d.mode : "…"}
        <EnvStatus env={env} loading={loading} />
        <span className="dim"> · ENTER SHOWS HASH · E CSV · F5</span>
      </div>
      <ErrorLine error={error} hasData={!!d} usage="ADDR <0x ADDRESS | GAS> [ETH|ARB|OP|BASE|POLY|BSC]" />
      {d?.address && (
        <div className="line" data-testid="addr-summary">
          {d.address} · BALANCE {d.balance ? <span className="acc">{fmtCoin(d.balance.balance)} {d.coin}</span> : <span className="warn">NOT LOADED</span>}
        </div>
      )}
      {d?.gas && (
        <div className="line" data-testid="addr-gas">
          GAS (GWEI) SAFE {fmtGwei(d.gas.safe)} · STANDARD {fmtGwei(d.gas.propose)} · FAST {fmtGwei(d.gas.fast)} · BASE FEE {fmtGwei(d.gas.base_fee)}
          <span className="dim"> · AS OF BLOCK {d.gas.last_block ?? "?"}</span>
        </div>
      )}
      {d?.notes.map((n) => (
        <div key={n} className="warn">{n}</div>
      ))}
      {picked && <div className="line dim">HASH {picked}</div>}
      {d && <div className="dim">{d.note}</div>}
      {d?.mode === "ADDRESS" && (d.txs ? <Grid ref={grid} columns={columns} rows={txs} /> : <div className="dim">TRANSACTIONS NOT LOADED</div>)}
      {d?.mode === "ADDRESS" && d.txs && d.txs.length === 0 && <div className="dim">NO TRANSACTIONS ON THIS CHAIN FOR THIS ADDRESS</div>}
    </div>
  );
}
