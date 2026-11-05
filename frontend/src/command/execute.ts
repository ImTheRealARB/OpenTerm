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
import { getSettings, updateSettings } from "../settings/runtime";

export { statusMsg, type StatusMsg } from "./status";

// The THEME / SETTINGS argument parser is only needed by those two commands, so it lives in its own chunk (not the
// startup bundle). main.tsx asks for it while the browser is idle, so by the time anyone types THEME it is nearly
// always here and `execute` stays synchronous.
type SettingsCommands = typeof import("../settings/commands");
let settingsCommands: SettingsCommands | undefined;
export function preloadSettingsCommands(): Promise<unknown> {
  return import("../settings/commands").then((m) => (settingsCommands = m));
}

/**
 * Parses and runs a command. Returns true on success (command line clears).
 * `replay` is internal: the same input run a second time (see the THEME / SETTINGS case below), so it is not
 * written to the command history twice.
 */
export function execute(input: string, opts: { newPanel?: boolean; replay?: boolean } = {}): boolean {
  const parsed = parseCommand(input, isFunction);
  if (!parsed.ok) return fail(parsed.error);
  if (!opts.replay) history.push(parsed.raw.toUpperCase());
  // An alias (WCRS, MOST ...) runs its canonical function, so panels and saved layouts only ever hold canonical codes.
  if (parsed.fn) parsed.fn = FUNCTIONS.get(parsed.fn)?.code ?? parsed.fn;

  if (parsed.fn === "LAYOUT" || parsed.fn === "MONITOR") {
    statusMsg.set(() => null);
    const done = layoutCommand(parsed.args);
    if (done !== null) return done;
  }

  let args = parsed.args;
  // Phase 10: THEME name / SETTINGS key value apply at once and stay on the current panel;
  // bare THEME or SETTINGS opens the SETTINGS panel.
  let fnOverride: string | undefined;
  // Phase 11: SETTINGS APIKEYS [PROVIDER] is the APIKEYS panel.
  if (parsed.fn === "SETTINGS" && args[0]?.toUpperCase() === "APIKEYS") {
    fnOverride = "APIKEYS";
    args = args.slice(1);
  } else if (parsed.fn === "THEME" || parsed.fn === "SETTINGS") {
    if (!settingsCommands) {
      // Chunk not downloaded yet (only in the first moments after startup): fetch it, then run this same command again.
      void preloadSettingsCommands().then(() => execute(input, { ...opts, replay: true }));
      return true;
    }
    const cmd = (parsed.fn === "THEME" ? settingsCommands.themeArgs : settingsCommands.settingsArgs)(args, getSettings());
    if (cmd && !cmd.ok) return fail(cmd.error);
    if (cmd?.checkFont) {
      // A custom font is applied only after confirming it is installed here; a missing one is an error, not a silent fallback.
      const name = cmd.checkFont;
      void import("../settings/fontCheck").then(({ fontInstalled }) => {
        if (!fontInstalled(name)) return fail(`FONT "${name}" IS NOT INSTALLED ON THIS COMPUTER. INSTALL IT, THEN TRY AGAIN`);
        updateSettings(() => cmd.next);
        info(cmd.message);
      });
      return true;
    }
    if (cmd) {
      updateSettings(() => cmd.next);
      info(cmd.message);
      return true;
    }
    fnOverride = "SETTINGS";
  }
  // Phase 15: PORT OPT / PORT ATTR are the OPT / ATTR panels; every other PORT argument stays with the PORT panel below.
  if (parsed.fn === "PORT" && (args[0]?.toUpperCase() === "OPT" || args[0]?.toUpperCase() === "ATTR")) {
    fnOverride = args[0].toUpperCase();
    args = args.slice(1);
  }
  // Phase 15: CORR REGIME is the REGIME panel; every other CORR argument stays with the CORR panel.
  if (parsed.fn === "CORR" && args[0]?.toUpperCase() === "REGIME") {
    fnOverride = "REGIME";
    args = args.slice(1);
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
  if ((parsed.fn === "PORT" && !fnOverride) || parsed.fn === "ALRT") {
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
