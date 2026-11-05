/**
 * How GUI controls run things: they never have their own logic, they hand ordinary command-line text to the same
 * `execute()` the command line uses (parsing, history, sticky security, "needs a security" errors, panel loading).
 */
import { execute } from "../command/execute";
import { focusCommandLine } from "./chrome";

/** Runs command text in the focused panel, then returns focus to the command line. Returns true on success. */
export function runCommand(text: string): boolean {
  const ok = execute(text);
  focusCommandLine();
  return ok;
}

/** Like `runCommand`, but free text ("apple vs microsoft") goes through the command line's plain-English path (lazy chunk). */
export const runTyped = (text: string): Promise<boolean> => import("./runTyped").then((m) => m.runTyped(text));
