/**
 * KITE (Phase 15): login state of the read-only Kite Connect data source. L opens the backend's `/api/kite/login` in a new tab (the backend
 * redirects to Kite; this app never sees the api key or secret), X logs out, R refreshes. There is nothing else here: no trading of any kind.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { registerPanelKeys } from "../keys/panelKeys";
import { kiteApi, type ApiError, type KiteStatus } from "../net/api";
import { kite, refreshKite } from "../net/kite";
import { useStore } from "../state/store";
import { replaceView } from "../state/workspace";
import { kiteArgs } from "./quantArgs";
import type { FunctionProps } from "./registry";

const USAGE = "USAGE: KITE [LOGIN|STATUS|LOGOUT]";
const CLS: Record<string, string> = { OK: "up", "LOGGED OUT": "warn", "KITE LOGIN EXPIRED": "err", "NO KEY": "dim" };

export function openKiteLogin(): boolean {
  // The route answers with a redirect to Kite; no noopener so the tab can be checked, but nothing from it is read.
  return window.open(kiteApi.loginUrl, "_blank") !== null;
}

export default function KITE({ panelId, args }: FunctionProps) {
  const st = useStore(kite, (s) => s);
  const [loaded, setLoaded] = useState(false);
  const [msg, setMsg] = useState<{ text: string; cls: string } | null>(null);
  const { params, bad } = kiteArgs(args);
  const action = bad.length ? "bad" : params.action;

  const refresh = useCallback(async () => {
    await refreshKite();
    setLoaded(true);
  }, []);

  const login = useCallback(() => {
    if (openKiteLogin()) setMsg({ text: "LOGIN OPENED IN A NEW TAB: SIGN IN THERE, THEN PRESS R", cls: "dim" });
    else setMsg({ text: "THE BROWSER BLOCKED THE NEW TAB: PRESS L", cls: "warn" });
  }, []);

  const logout = useCallback(async () => {
    try {
      const s: KiteStatus = await kiteApi.logout();
      setMsg({ text: `KITE LOGGED OUT${s.state ? `: ${s.state}` : ""}`, cls: "dim" });
    } catch (e) {
      setMsg({ text: `LOGOUT FAILED: ${(e as ApiError).message}`, cls: "err" });
    }
    await refresh();
  }, [refresh]);

  // `KITE LOGIN` / `KITE LOGOUT` act once, then the view goes back to plain status so a remount does not repeat them.
  const acted = useRef(false);
  useEffect(() => {
    void refresh();
    if (acted.current) return;
    if (action === "login" || action === "logout") {
      acted.current = true;
      if (action === "login") login();
      else void logout();
      replaceView(panelId, (v) => ({ ...v, args: [] }));
    }
  }, [action, panelId, refresh, login, logout]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        if (e.ctrlKey || e.altKey || e.metaKey) return false;
        switch (e.key) {
          case "l":
            login();
            return true;
          case "x":
            void logout();
            return true;
          case "r":
          case "F5":
            setMsg(null);
            void refresh();
            return true;
        }
        return false;
      }),
    [panelId, login, logout, refresh],
  );

  if (action === "bad") {
    return (
      <div className="fn">
        <div className="line err">{USAGE}</div>
      </div>
    );
  }
  return (
    <div className="fn" data-testid="kite-panel">
      <div className="line">
        <span className="acc">KITE CONNECT</span> READ-ONLY DATA SOURCE
        {!loaded && <span className="dim"> · LOADING…</span>}
        <span className="dim"> · L LOGIN · X LOGOUT · R REFRESH</span>
      </div>
      {st ? (
        <>
          <div>
            STATE <span className={CLS[st.state] ?? "warn"}>{st.state}</span>
          </div>
          {st.message && <div className={st.state === "OK" ? "dim" : "warn"}>{st.message}</div>}
          <div>
            USER <span className="acc">{st.user || "-"}</span>
            {st.logged_in_at && <span className="dim"> · LOGGED IN {st.logged_in_at}</span>}
          </div>
          {st.expires_note && <div className="dim">{st.expires_note}</div>}
          {st.state === "NO KEY" && <div className="dim">KEY REQUIRED: set KITE_API_KEY in APIKEYS</div>}
        </>
      ) : (
        loaded && <div className="err">STATE UNKNOWN: KITE STATUS UNAVAILABLE (BACKEND DOWN?)</div>
      )}
      {msg && <div className={msg.cls}>{msg.text}</div>}
    </div>
  );
}
