import { FUNCTIONS, isFunction } from "../functions/registry";
import { commandStart } from "../perf/metrics";
import { currentView, navigate, split, workspace } from "../state/workspace";
import { history } from "./history";
import { layoutCommand } from "./layouts";
import { parseCommand } from "./parser";
import { fail, statusMsg } from "./status";

export { statusMsg, type StatusMsg } from "./status";

/** Parses and runs a command. Returns true on success (command line clears). */
export function execute(input: string, opts: { newPanel?: boolean } = {}): boolean {
  const parsed = parseCommand(input, isFunction);
  if (!parsed.ok) return fail(parsed.error);
  history.push(parsed.raw.toUpperCase());

  if (parsed.fn === "LAYOUT" || parsed.fn === "MONITOR") {
    statusMsg.set(() => null);
    const done = layoutCommand(parsed.args);
    if (done !== null) return done;
  }

  const s = workspace.get();
  let panelId = parsed.target ?? s.focus;
  if (parsed.target && !s.panels[parsed.target]) return fail(`NO PANEL ${parsed.target}`);
  if (opts.newPanel && !parsed.target) {
    const id = split("v");
    if (id === null) return fail("PANEL LIMIT (9) REACHED");
    panelId = id;
  }

  const sticky = currentView(workspace.get().panels[panelId]).security;
  const fn = parsed.fn ?? "DES";
  const def = FUNCTIONS.get(fn)!;
  // Security context is sticky per panel, even across functions that don't use it.
  const security = parsed.security ?? sticky;
  if (def.needsSecurity && !security) return fail(`${fn} NEEDS A SECURITY, E.G. AAPL ${fn}`);
  if (parsed.security) history.addRecentSecurity(parsed.security.symbol);

  statusMsg.set(() => null);
  commandStart(panelId, parsed.raw);
  navigate(panelId, { fn, security, args: parsed.args });
  return true;
}
