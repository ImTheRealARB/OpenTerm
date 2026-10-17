/**
 * Phase 11: the shared KEY REQUIRED line. Amber (a missing key is a setup state, not a failure). While it shows,
 * Enter in the focused panel opens APIKEYS on that provider. Used by every shared error line (secPanel, macroUi).
 */
import { useEffect } from "react";
import { registerPanelKeys } from "../keys/panelKeys";
import type { ApiError } from "../net/api";
import { keyRequiredOf } from "../net/api";
import { usePanelId } from "../state/panelContext";
import { currentView, navigate, workspace } from "../state/workspace";

export function KeyRequiredLine({ error }: { error: ApiError }) {
  const info = keyRequiredOf(error);
  const panelId = usePanelId();
  const key = info?.key;
  useEffect(() => {
    if (!key || !panelId) return;
    return registerPanelKeys(panelId, (e) => {
      if (e.key !== "Enter" || e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return false;
      const p = workspace.get().panels[panelId];
      if (p) navigate(panelId, { fn: "APIKEYS", security: currentView(p).security, args: [key] });
      return true;
    });
  }, [panelId, key]);
  if (!info) return null;
  return (
    <div className="keyreq warn">
      {info.detail} <span className="dim">· ENTER OPENS APIKEYS {info.key}</span>
    </div>
  );
}

/** True when this failure is the 424 envelope (callers then render KeyRequiredLine instead of the red line). */
export const isKeyRequired = (error: ApiError | null | undefined): boolean => keyRequiredOf(error) !== null;
