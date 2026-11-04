/**
 * How GUI controls run things: they never have their own logic, they hand ordinary command-line text to the same
 * `execute()` the command line uses (parsing, history, sticky security, "needs a security" errors, panel loading).
 */
import { execute } from "../command/execute";
import { needsNatural, resolveNatural } from "../command/nlRun";
import { fail, info } from "../command/status";
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

/**
 * Like `runCommand`, but free text that is not a command ("apple stock price chart", "apple vs microsoft") goes through the
 * same plain-English path as the command line. Exact codes and tickers take the synchronous route unchanged.
 */
export async function runTyped(text: string): Promise<boolean> {
  if (!needsNatural(text)) return runCommand(text);
  const r = await resolveNatural(text).catch(() => ({ kind: "asis" }) as const);
  if (r.kind === "command") {
    const ok = runCommand(r.command);
    if (ok) info(`${text.trim().toUpperCase()} -> ${r.command}`);
    return ok;
  }
  if (r.kind === "choices") info(`DID YOU MEAN: ${r.choices.slice(0, 3).map((c) => c.label).join(" / ")}`);
  else if (r.kind === "error") fail(r.message);
  else return runCommand(text);
  focusCommandLine();
  return false;
}

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
