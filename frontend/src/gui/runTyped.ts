import { needsNatural, resolveNatural } from "../command/nlRun";
import { fail, info } from "../command/status";
import { focusCommandLine } from "./chrome";
import { runCommand } from "./run";

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

