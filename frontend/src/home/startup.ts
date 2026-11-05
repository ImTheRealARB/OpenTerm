/**
 * Start-up choice (setting `startup`): a new session either opens the HOME page or restores the saved workspace.
 *
 * "A new session" = a new browser tab / window: the flag below lives in sessionStorage, which survives a page reload
 * (so F5 keeps your panels) but not a closed tab. Saved named layouts are untouched either way (LAYOUT LOAD, Ctrl+O),
 * and the HOME command brings the page back at any time.
 *
 * This file is imported by main.tsx, so it must stay tiny: no React, nothing from the HOME page itself.
 */
import type { Startup } from "../settings/schema";
import type { WorkspaceState } from "../state/workspace";

const SESSION_FLAG = "openterm.homed";

/** One panel showing HOME. */
export function homeWorkspace(): WorkspaceState {
  return {
    layout: { t: "leaf", id: 1 },
    panels: { 1: { id: 1, views: [{ fn: "HOME", args: [] }], pos: 0 } },
    focus: 1,
    maximized: null,
  };
}

/** Pure decision: open HOME only for "home" and only once per session. */
export const shouldOpenHome = (startup: Startup, alreadyDone: boolean): boolean => startup === "home" && !alreadyDone;

/** Called once at cold start (before the first render). Returns true when it replaced the workspace with HOME. */
export function openHomeOnStart(
  startup: Startup,
  apply: (w: WorkspaceState) => void,
  storage: Pick<Storage, "getItem" | "setItem"> | null = typeof sessionStorage === "undefined" ? null : sessionStorage,
): boolean {
  // Storage blocked (private mode, tests): we cannot tell whether this is a reload, so leave the workspace alone.
  if (!storage) return false;
  let done: boolean;
  try {
    done = storage.getItem(SESSION_FLAG) !== null;
    storage.setItem(SESSION_FLAG, "1");
  } catch {
    return false;
  }
  if (!shouldOpenHome(startup, done)) return false;
  apply(homeWorkspace());
  return true;
}
