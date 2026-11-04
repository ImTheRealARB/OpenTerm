/**
 * How GUI controls run things: they never have their own logic, they hand ordinary command-line text to the same
 * `execute()` the command line uses (parsing, history, sticky security, "needs a security" errors, panel loading).
 */
import { execute } from "../command/execute";
import { FUNCTIONS, isFunction } from "../functions/registry";
import { currentView, workspace } from "../state/workspace";
import { focusCommandLine } from "./chrome";
import { symbolCommand } from "./search";

/** Runs command text in the focused panel, then returns focus to the command line. Returns true on success. */
export function runCommand(text: string): boolean {
  const ok = execute(text);
  focusCommandLine();
  return ok;
}

/** Like `runCommand`, but free text ("apple vs microsoft") goes through the command line's plain-English path (lazy chunk). */
export const runTyped = (text: string): Promise<boolean> => import("./runTyped").then((m) => m.runTyped(text));

/** Symbol picker: loads a security into the focused panel (keeping its function when that function takes a security). */
export function runSymbol(text: string): boolean | Promise<boolean> {
  const s = workspace.get();
  const panel = s.panels[s.focus];
  const cmd = symbolCommand(text, {
    currentFn: panel ? currentView(panel).fn : undefined,
    isFunction,
    needsSecurity: (code) => FUNCTIONS.get(code)?.needsSecurity === true,
  });
  if (cmd === null) return false;
  return /\s/.test(cmd) ? runTyped(cmd) : runCommand(cmd);
}
