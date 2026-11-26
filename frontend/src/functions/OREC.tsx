/**
 * OREC (Phase 28): the option chain recorder. It snapshots the chains of ONE watchlist once per weekday after the US close
 * (off by default). `OREC <WATCHLIST>` turns it on for that list, `OREC OFF` turns it off, `OREC` shows the status and, for the
 * panel's security, the IV rank and the ATM IV by expiry. Every number says RECORDED BY OPENTERM SINCE <first day>.
 */
import { useEffect, useState } from "react";
import { PanelNote } from "../components/PanelNote";
import { fmtNum, fmtPct, fmtPrice } from "../format";
import { optionsRecApi } from "../net/optionsRecApi";
import type { OptionRecStatus, OptionRecSymbol } from "../net/types";
import type { FunctionProps } from "./registry";

const pct = (v: number | null | undefined) => (v == null ? "—" : fmtPct(v * 100));
const day = (epoch: number) => new Date(epoch * 1000).toISOString().slice(0, 10);

export default function OREC({ security, args }: FunctionProps) {
  const [status, setStatus] = useState<OptionRecStatus | null>(null);
  const [sym, setSym] = useState<OptionRecSymbol | null>(null);
  const [error, setError] = useState<string | null>(null);
  const word = (args[0] ?? "").toUpperCase();
  const symbol = security?.symbol;
  useEffect(() => {
    let alive = true;
    setError(null);
    setSym(null);
    (async () => {
      // a word after OREC changes the setting first; the status below then shows the new state
      if (word) await optionsRecApi.set(word === "OFF" ? null : word);
      const [st, s] = await Promise.all([optionsRecApi.status(), symbol ? optionsRecApi.symbol(symbol) : Promise.resolve(null)]);
      if (alive) { setStatus(st); setSym(s); }
    })().catch((e: Error) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [word, symbol]);
  const last = status?.last;
  const latestTerm = sym?.term?.[sym.term.length - 1];
  return (
    <div className="fn orec">
      <div className="line"><span className="acc">OREC </span>{symbol ?? ""}</div>
      {error && <PanelNote kind="error">ERR: {error}</PanelNote>}
      {!status && !error && <div className="line dim">LOADING</div>}
      {status && (
        <>
          <div className="line">
            RECORDER {status.watchlist ? <span className="up">ON · WATCHLIST {status.watchlist}</span> : <span className="warn">OFF · OREC &lt;WATCHLIST&gt; TURNS IT ON</span>}
          </div>
          <div className="line dim">{status.label} · {status.schedule}</div>
          {last && (
            <div className="line">
              LAST RUN {last.day}: {last.recorded.length} RECORDED
              {last.failed.length ? <span className="warn"> · {last.failed.length} FAILED: {last.failed.slice(0, 5).map((f) => `${f.symbol} (${f.error})`).join("; ")}</span> : null}
            </div>
          )}
        </>
      )}
      {symbol && sym && !sym.recorded && <PanelNote kind="error">{sym.message}</PanelNote>}
      {symbol && sym?.recorded && (
        <>
          <div className="line">
            IV RANK <span className="acc">{pct(sym.iv_rank)}</span> · IV PERCENTILE <span className="acc">{pct(sym.iv_percentile)}</span>
            {" "}· ATM IV {pct(sym.atm_iv)} · EM {sym.em_pct == null ? "—" : `${fmtNum(sym.em_pct, 1)}%`} · SPOT {fmtPrice(sym.spot)} · PCR {sym.pcr == null ? "—" : fmtNum(sym.pcr, 2)}
          </div>
          <div className="dim legend">{sym.label} · {sym.rank_note} · {sym.days_recorded} DAYS RECORDED</div>
          {latestTerm && (
            <table className="tbl">
              <thead><tr><th>EXPIRY</th><th>DAYS</th><th>ATM IV ({latestTerm.day})</th></tr></thead>
              <tbody>
                {latestTerm.points.map((p) => (
                  <tr key={p.expiry}><td>{day(p.expiry)}</td><td>{p.days}</td><td>{pct(p.atm_iv)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
