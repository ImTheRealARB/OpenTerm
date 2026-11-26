/**
 * NB (Phase 31): a local JupyterLab with openterm-sdk and example notebooks.
 *
 *   NB   status. Keys: S start, Enter open JupyterLab in the browser, X stop, F5 refresh.
 *
 * Nothing starts until you press S. The server runs `uv run --extra notebook jupyter lab` from the backend folder, bound to
 * 127.0.0.1 with a random token; your notebooks live next to the OpenTerm database (`<data folder>/notebooks`), and the examples are
 * copied there once. Needs a source checkout with uv (the desktop app cannot start it). It stops when OpenTerm stops.
 */
import { useCallback, useEffect, useState } from "react";
import { get, send } from "../net/core";
import { registerPanelKeys } from "../keys/panelKeys";
import { useLatest } from "../state/useLatest";
import { usePanelRefresh } from "./panelRefresh";
import type { FunctionProps } from "./registry";
import { openUrl } from "./secPanel";

interface NbStatus {
  running: boolean;
  dir: string;
  port: number | null;
  since: number | null;
  url?: string;
  exit_code?: number;
  examples: string[];
}

const POLL_MS = 3_000; // JupyterLab takes a few seconds to come up (longer on the first start, while uv installs it)

export default function NB({ panelId }: FunctionProps) {
  const [st, setSt] = useState<NbStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const latest = useLatest({ st });

  const refresh = useCallback(async () => {
    try {
      setSt((await get<{ data: NbStatus }>("/api/nb", undefined, 0, true)).data);
      setError(null);
    } catch (e) {
      setError(`COULD NOT READ NB STATUS: ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(t);
  }, [refresh]);
  usePanelRefresh(panelId, () => void refresh());

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        const cur = latest.current.st;
        const k = e.key.toLowerCase();
        if (k === "s") {
          setNote("STARTING JUPYTERLAB (THE FIRST START INSTALLS IT WITH uv: A MINUTE OR TWO)...");
          send<{ data: NbStatus }>("POST", "/api/nb/start").then(
            (r) => {
              setSt(r.data);
              setNote("STARTED: PRESS ENTER TO OPEN IT ONCE IT ANSWERS");
            },
            (err: Error) => setError(err.message),
          );
          return true;
        }
        if (k === "x") {
          send<{ data: NbStatus }>("POST", "/api/nb/stop").then((r) => { setSt(r.data); setNote("STOPPED"); }, (err: Error) => setError(err.message));
          return true;
        }
        if (e.key === "Enter") {
          if (cur?.url) openUrl(cur.url);
          else setNote(cur?.running ? "NO LINK: OPEN NB ON THE COMPUTER RUNNING OPENTERM" : "NOT RUNNING: PRESS S TO START");
          return true;
        }
        return false;
      }),
    [panelId, latest],
  );

  return (
    <div className="fn">
      <div className="line">
        <span className="acc">NB</span> LOCAL JUPYTERLAB WITH OPENTERM-SDK <span className="dim"> · S START · ENTER OPEN · X STOP · F5</span>
      </div>
      {st && (
        <div className="line" data-testid="nb-state">
          {st.running ? <span className="up">RUNNING ON 127.0.0.1:{st.port}</span> : <span className="dim">NOT RUNNING</span>}
          {st.exit_code != null && !st.running ? <span className="warn"> · LAST RUN EXITED WITH CODE {st.exit_code}</span> : null}
        </div>
      )}
      {st && <div className="line dim">NOTEBOOK FOLDER: {st.dir}</div>}
      {st && <div className="line dim">EXAMPLES (COPIED THERE ONCE): {st.examples.join(", ") || "NONE"}</div>}
      <div className="line dim">NEEDS A SOURCE CHECKOUT WITH uv; THE SERVER STOPS WITH OPENTERM. READ ONLY: THE SDK CANNOT PLACE ORDERS.</div>
      {note && <div className="line">{note}</div>}
      {error && <div className="line err">{error}</div>}
    </div>
  );
}
