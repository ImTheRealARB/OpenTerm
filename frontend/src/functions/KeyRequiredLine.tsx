/**
 * Phase 11: the shared KEY REQUIRED line. Amber (a missing key is a setup state, not a failure). While it shows,
 * Enter in the focused panel opens APIKEYS on that provider. Used by every shared error line (secPanel, macroUi).
 */
import { useEffect } from "react";
import { PanelNote } from "../components/PanelNote";
import { registerPanelKeys } from "../keys/panelKeys";
import { type ApiError, keyRequiredOf } from "../net/core";
import { settingsStore } from "../settings/runtime";
import { usePanelId } from "../state/panelContext";
import { useStore } from "../state/store";
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
  return <KeyNeeded text={info.detail} keyName={info.key} enterOpens />;
}

/**
 * The visible part of a KEY REQUIRED message. Terminal mode: the amber line (Enter opens APIKEYS, see above).
 * GUI mode: a PanelNote with the same exact text, one plain sentence and an "Open API keys" button.
 * Panels that print their own "KEY REQUIRED: set X in APIKEYS" text use this too, so every one looks the same.
 */
export function KeyNeeded({ text, keyName, enterOpens = false }: { text: string; keyName: string; enterOpens?: boolean }) {
  const gui = useStore(settingsStore, (s) => s.mode === "gui");
  const panelId = usePanelId();
  if (!gui)
    return (
      <div className="keyreq warn">
        {text} {enterOpens && <span className="dim">· ENTER OPENS APIKEYS {keyName}</span>}
      </div>
    );
  const open = () => {
    const p = workspace.get().panels[panelId];
    if (p) navigate(panelId, { fn: "APIKEYS", security: currentView(p).security, args: [keyName] });
  };
  return (
    // The wrapper only recolours the message amber (a missing key is a setup state, not a failure).
    <div className="keyreq">
      <PanelNote kind="stale" actions={panelId ? [{ label: "Open API keys", onClick: open }] : []}>
        {text}
      </PanelNote>
    </div>
  );
}

/** True when this failure is the 424 envelope (callers then render KeyRequiredLine instead of the red line). */
export const isKeyRequired = (error: ApiError | null | undefined): boolean => keyRequiredOf(error) !== null;
