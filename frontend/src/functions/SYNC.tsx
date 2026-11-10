/**
 * SYNC (Phase 18 step 2): READ-ONLY broker sync into PORT. `SYNC` shows both brokers, `SYNC KITE|IBKR [PORTFOLIO]` one of them.
 * K syncs Kite, I syncs IBKR, S syncs the broker on screen, R reloads the status. A sync replaces only the lots it wrote earlier
 * (labelled with their source and time); manual lots are never touched. There is no order of any kind here.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { refreshPortfolios } from "../command/portfolios";
import { registerPanelKeys } from "../keys/panelKeys";
import type { ApiError } from "../net/core";
import { syncApi, type Broker, type BrokerStatus, type SyncRecord, type SyncStatus } from "../net/syncApi";
import { replaceView } from "../state/workspace";
import { usePanelRefresh } from "./panelRefresh";
import type { FunctionProps } from "./registry";
import { countsLine, diffLines, headline, noDifference, parseSyncArgs, SYNC_USAGE, ageText, type SyncArgs } from "./syncModel";

const NAME: Record<Broker, string> = { kite: "ZERODHA KITE", ibkr: "INTERACTIVE BROKERS" };

export default function SYNC({ panelId, args }: FunctionProps) {
  const parsed = useMemo(() => parseSyncArgs(args), [args]);
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<Broker | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [fresh, setFresh] = useState<Partial<Record<Broker, SyncRecord>>>({});
  const [failure, setFailure] = useState<Partial<Record<Broker, string>>>({});
  const [now, setNow] = useState(() => Date.now() / 1000);
  const cfg = "error" in parsed ? null : parsed;
  const latest = useRef<{ cfg: SyncArgs | null; status: SyncStatus | null; busy: Broker | null }>({ cfg, status, busy });
  latest.current = { cfg, status, busy };

  const load = useCallback(async () => {
    try {
      setStatus(await syncApi.status());
      setLoadErr(null);
    } catch (e) {
      setLoadErr((e as ApiError).message);
    }
    setNow(Date.now() / 1000);
  }, []);

  const run = useCallback(
    async (broker: Broker) => {
      const { cfg: c, status: st, busy: b } = latest.current;
      if (b) return;
      const portfolio = (c?.broker === broker ? c.portfolio : null) ?? st?.default_portfolio[broker] ?? undefined;
      setBusy(broker);
      setFailure((f) => ({ ...f, [broker]: undefined }));
      try {
        const rec = broker === "kite" ? await syncApi.kite(portfolio, c?.broker === "kite" && c.positions) : await syncApi.ibkr(portfolio, c?.broker === "ibkr" ? (c.account ?? undefined) : undefined);
        setFresh((f) => ({ ...f, [broker]: rec }));
        void refreshPortfolios();
      } catch (e) {
        setFailure((f) => ({ ...f, [broker]: (e as ApiError).message }));
      }
      setBusy(null);
      await load();
    },
    [load],
  );

  // `SYNC KITE GO` runs once, then the view goes back to the plain status so a remount does not run it again.
  const acted = useRef(false);
  useEffect(() => {
    void load();
    if (acted.current || !cfg?.go || !cfg.broker) return;
    acted.current = true;
    void run(cfg.broker);
    replaceView(panelId, (v) => ({ ...v, args: v.args.filter((a) => a.toUpperCase() !== "GO") }));
  }, [cfg, load, run, panelId]);

  usePanelRefresh(panelId, () => {
    void load();
  });
  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const only = latest.current.cfg?.broker;
        switch (e.key) {
          case "k":
            void run("kite");
            return true;
          case "i":
            void run("ibkr");
            return true;
          case "s":
            if (only) void run(only);
            else setHint("S NEEDS A BROKER ON SCREEN: SYNC KITE OR SYNC IBKR (OR PRESS K / I)");
            return true;
          case "r":
            void load();
            return true;
        }
        return false;
      }),
    [panelId, run, load],
  );

  if ("error" in parsed)
    return (
      <div className="fn">
        <div className="line err">{parsed.error}</div>
        <div className="line dim">{SYNC_USAGE}</div>
      </div>
    );
  const brokers: Broker[] = parsed.broker ? [parsed.broker] : ["kite", "ibkr"];
  return (
    <div className="fn" data-testid="sync-panel">
      <div className="line">
        <span className="acc">SYNC</span> READ-ONLY BROKER SYNC INTO PORT
        <span className="dim legend"> · K KITE · I IBKR · S THIS BROKER · R RELOAD</span>
      </div>
      {hint && <div className="warn">{hint}</div>}
      {loadErr && <div className="err">ERR: SYNC STATUS UNAVAILABLE ({loadErr})</div>}
      {!status && !loadErr && <div className="dim">LOADING…</div>}
      {status && brokers.map((b) => <BrokerBlock key={b} broker={b} st={status[b]} fresh={fresh[b]} failure={failure[b]} busy={busy === b} now={now} target={parsed.broker === b ? parsed.portfolio : null} fallback={status.default_portfolio[b]} />)}
      <div className="dim">SYNC ONLY READS THE BROKER. LOTS IT WRITES ARE LABELLED WITH THEIR SOURCE; MANUAL LOTS ARE NEVER CHANGED. NO ORDERS.</div>
    </div>
  );
}

function BrokerBlock({ broker, st, fresh, failure, busy, now, target, fallback }: { broker: Broker; st: BrokerStatus; fresh?: SyncRecord; failure?: string; busy: boolean; now: number; target: string | null; fallback: string }) {
  const rec = fresh ?? st.last_ok;
  const h = headline(broker, rec, st.last_error, now);
  const extra = broker === "kite" ? st.login : null;
  return (
    <div className="sync-block">
      <div>
        <span className="acc">{NAME[broker]}</span> → PORT {target ?? fallback}
        {busy && <span className="warn"> · SYNCING…</span>}
      </div>
      <div className={h.cls}>{h.text}</div>
      {broker === "kite" && extra && extra.state !== "OK" && <div className="warn">{extra.message ?? extra.state}</div>}
      {broker === "ibkr" && st.gateway_url && <div className="dim">GATEWAY {st.gateway_url} (LOOPBACK ONLY)</div>}
      {failure && <div className="err">ERR: {failure}</div>}
      {!failure && st.last_error && (!rec || st.last_error.at > rec.at) && <div className="err">ERR {ageText(st.last_error.at, now)}: {st.last_error.error}</div>}
      {rec && (
        <>
          <div>{countsLine(rec)}</div>
          {rec.diff && (noDifference(rec.diff) ? <div className="dim">NO DIFFERENCE FROM THE PREVIOUS SYNC</div> : <div className="dim">DIFFERENCE FROM THE PREVIOUS SYNC</div>)}
          {diffLines(rec.diff).map((l) => (
            <div key={l} className={l.startsWith("+") ? "up" : l.startsWith("-") ? "warn" : ""}>{l}</div>
          ))}
          {rec.conflicts.map((c) => (
            <div key={c} className="warn">CONFLICT {c}</div>
          ))}
          {rec.warnings.map((w) => (
            <div key={w} className="warn">NOTE {w}</div>
          ))}
          {rec.skipped.slice(0, 8).map((s) => (
            <div key={s.symbol + s.reason} className="dim">SKIPPED {s.reason}</div>
          ))}
          {rec.skipped.length > 8 && <div className="dim">… {rec.skipped.length - 8} MORE SKIPPED</div>}
          {rec.cash?.map((a) => (
            <div key={a.account} className="dim">
              CASH {a.account}: {a.rows.map((r) => `${r.base ? "TOTAL(BASE)" : r.currency} ${r.cash === null ? "-" : r.cash.toLocaleString("en-US", { maximumFractionDigits: 2 })}`).join(" · ")}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
