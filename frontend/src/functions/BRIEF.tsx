/**
 * BRIEF: the last daily brief (Phase 17 C). The backend builds it (watchlist movers, macro, news...) and keeps the
 * latest one; this panel only displays it. R builds a fresh one now, S builds it and sends it to the delivery channels.
 * Each section names its source and age, or says STALE / the error: a missing section is shown, never hidden.
 */
import { useCallback, useEffect, useState } from "react";
import { PanelNote } from "../components/PanelNote";
import { fmtAge } from "../format";
import { registerPanelKeys } from "../keys/panelKeys";
import { briefApi } from "../net/briefApi";
import type { Brief } from "../net/types";
import { briefStamp, sectionMeta } from "./dlvrFields";
import type { FunctionProps } from "./registry";

export default function BRIEF({ panelId }: FunctionProps) {
  // `brief === undefined` = still loading the first answer; `null` = the backend has none yet.
  const [brief, setBrief] = useState<Brief | null | undefined>(undefined);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    briefApi.get().then(
      (r) => setBrief(r.brief),
      (e) => {
        setErr(e instanceof Error ? e.message : String(e));
        setBrief(null);
      },
    );
  }, []);

  const run = useCallback(async (sendIt: boolean) => {
    setBusy(true);
    setErr(null);
    setNote(null);
    try {
      const r = await briefApi.run(sendIt);
      setBrief(r.brief);
      if (sendIt) {
        const sent = (r.delivered ?? []).filter((d) => d.status === "ok" || d.status === "sent").length;
        setNote(`SENT TO ${sent} CHANNEL${sent === 1 ? "" : "S"}`);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        if (e.key === "r" || e.key === "R") {
          void run(false);
          return true;
        }
        if (e.key === "s" || e.key === "S") {
          void run(true);
          return true;
        }
        return false;
      }),
    [panelId, run],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">DAILY BRIEF</span>
        {brief && <span> {briefStamp(brief.at)}</span>}
        {brief?.watchlist && <span className="dim"> · WATCHLIST {brief.watchlist.toUpperCase()}</span>}
        {busy && <span className="dim"> · BUILDING…</span>}
        {note && <span className="up"> · {note}</span>}
        <span className="dim"> · R BUILD NOW · S BUILD AND SEND</span>
      </div>
      {err && <PanelNote kind="error">ERR: {err}</PanelNote>}
      {brief === undefined && !err && <PanelNote kind="loading">LOADING LAST BRIEF…</PanelNote>}
      {brief === null && !err && <PanelNote kind="empty">NO BRIEF YET: press R to build one</PanelNote>}
      {brief?.sections.map((s) => {
        const meta = sectionMeta(s, fmtAge);
        return (
          <div key={s.id} data-testid={`brief-${s.id}`} style={{ marginTop: 8 }}>
            <div>
              <span className="acc">{s.title.toUpperCase()}</span> <span className={meta.cls}>{meta.text}</span>
            </div>
            {s.lines.map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
