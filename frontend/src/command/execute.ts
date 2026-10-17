import { FUNCTIONS, isFunction } from "../functions/registry";
import { commandStart } from "../perf/metrics";
import { currentView, navigate, split, workspace } from "../state/workspace";
import { history } from "./history";
import { layoutCommand } from "./layouts";
import { parseCommand } from "./parser";
import { fail, info, statusMsg } from "./status";
import { deleteWatchlist, editWatchlist, parseWl } from "./watchlists";
import { alrtCommand } from "./alerts"; // Phase 8
import { portCommand } from "./portfolios"; // Phase 8
import { settingsArgs, themeArgs } from "../settings/commands";
import { getSettings, updateSettings } from "../settings/runtime";

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

  let args = parsed.args;
  // Phase 10: THEME name / SETTINGS key value apply at once and stay on the current panel;
  // bare THEME or SETTINGS opens the SETTINGS panel.
  let fnOverride: string | undefined;
  if (parsed.fn === "THEME" || parsed.fn === "SETTINGS") {
    const cmd = (parsed.fn === "THEME" ? themeArgs : settingsArgs)(args, getSettings());
    if (cmd && !cmd.ok) return fail(cmd.error);
    if (cmd) {
      updateSettings(() => cmd.next);
      info(cmd.message);
      return true;
    }
    fnOverride = "SETTINGS";
  }
  if (parsed.fn === "WL") {
    const act = parseWl(args, parsed.security);
    if (act.kind === "error") return fail(act.message);
    if (act.kind === "delete") {
      statusMsg.set(() => null);
      void deleteWatchlist(act.name);
      return true;
    }
    if (act.kind === "edit") {
      void editWatchlist(act.name, act.add, act.remove);
      args = [act.name]; // then show the list
    }
  }

  // --- Phase 8: PORT / ALRT edit first, then show the panel ---
  if (parsed.fn === "PORT" || parsed.fn === "ALRT") {
    const r = parsed.fn === "PORT" ? portCommand(args, parsed.security) : alrtCommand(args, parsed.security);
    if (typeof r === "boolean") return r;
    args = r;
  }

  const s = workspace.get();
  let panelId = parsed.target ?? s.focus;
  if (parsed.target && !s.panels[parsed.target]) return fail(`NO PANEL ${parsed.target}`);
  if (opts.newPanel && !parsed.target) {
    const id = split("v");
    if (id === null) return fail("PANEL LIMIT (9) REACHED");
    panelId = id;
  }

  const cur = currentView(workspace.get().panels[panelId]);
  const sticky = cur.security;
  const fn = fnOverride ?? parsed.fn ?? "DES";
  const def = FUNCTIONS.get(fn)!;
  // Security context is sticky per panel, even across functions that don't use it.
  const security = parsed.security ?? sticky;
  if (def.needsSecurity && !security) return fail(`${fn} NEEDS A SECURITY, E.G. AAPL ${fn}`);
  if (parsed.security) history.addRecentSecurity(parsed.security.symbol);

  statusMsg.set(() => null);
  // Editing the list a panel already shows: it refetches by itself, no new history entry.
  if (fn === "WL" && cur.fn === "WL" && args.length && cur.args[0]?.toUpperCase() === args[0]) return true;
  if ((fn === "PORT" || fn === "ALRT") && cur.fn === fn && (cur.args[0] ?? "").toUpperCase() === (args[0] ?? "")) return true; // Phase 8
  commandStart(panelId, parsed.raw);
  navigate(panelId, { fn, security, args });
  return true;
}
